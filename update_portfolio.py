import os
import shutil
import ast
import math
import operator
import re
from datetime import datetime
import pandas as pd
import matplotlib.pyplot as plt
from openpyxl import load_workbook
from openpyxl.chart import BarChart, PieChart, Reference
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

CELL_REF_RE = re.compile(r"(?<![A-Za-z0-9_])(\$?[A-Z]{1,3}\$?\d+)(?![A-Za-z0-9_])")
SUMMARY_START_ROW = 2
ASSET_TABLE_START_ROW = 8
SECTOR_WEIGHT_LIMIT = 20
SINGLE_ASSET_WEIGHT_LIMIT = 10
SECTOR_RISK_EXCLUSIONS = {"Cash", "Fixed Income"}
TRANSACTIONS_SHEET = "Transactions"
STATE_SHEET = "Portfolio_State"
SECTOR_LABELS = {
    "Banking": "Banking",
    "Telecommunication": "Telecom",
    "Insurance": "Insurance",
    "Energy": "Energy",
    "ETFs": "ETF",
    "Fixed Income": "Fixed Income",
    "Liquid Cash": "Cash",
}

DARK_OLIVE = "3B4436"
CREAM = "F1E9CB"
TEXT_DARK = "2F332E"
WARM_BEIGE = "E6DFD3"
WARM_WHITE = "FDFBF7"
SOFT_BEIGE = "EAECE6"
BORDER_COLOR = "B8AA91"
TRANSACTION_BASE_COLUMNS = [
    "Date",
    "Asset",
    "Action",
    "Quantity",
    "Price",
    "Broker",
    "Fees",
    "Benefits",
]
TRANSACTION_CALC_COLUMNS = [
    "Realized Gain",
    "Unrealized Gain",
    "Cost Basis",
    "Average Purchase Price",
    "Position Quantity",
]
TRANSACTION_COLUMNS = TRANSACTION_BASE_COLUMNS + TRANSACTION_CALC_COLUMNS
STATE_COLUMNS = ["Asset", "Sector", "Shares", "Current Price", "Market Value"]

ALLOWED_OPERATORS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
}

ALLOWED_UNARY_OPERATORS = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}


def evaluate_math_node(node):
    if isinstance(node, ast.Expression):
        return evaluate_math_node(node.body)

    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value

    if isinstance(node, ast.BinOp) and type(node.op) in ALLOWED_OPERATORS:
        return ALLOWED_OPERATORS[type(node.op)](
            evaluate_math_node(node.left),
            evaluate_math_node(node.right),
        )

    if isinstance(node, ast.UnaryOp) and type(node.op) in ALLOWED_UNARY_OPERATORS:
        return ALLOWED_UNARY_OPERATORS[type(node.op)](evaluate_math_node(node.operand))

    raise ValueError("Unsupported formula expression")


def numeric_cell_value(worksheet, coordinate, seen=None):
    coordinate = coordinate.replace("$", "")
    seen = seen or set()

    if coordinate in seen:
        raise ValueError(f"Circular formula reference at {coordinate}")

    seen.add(coordinate)
    value = worksheet[coordinate].value

    if isinstance(value, str) and value.startswith("="):
        return evaluate_excel_formula(worksheet, value, seen)

    return pd.to_numeric(value, errors="coerce")


def evaluate_excel_formula(worksheet, formula, seen=None):
    expression = formula.lstrip("=").replace("^", "**")

    def replace_cell_reference(match):
        value = numeric_cell_value(worksheet, match.group(1), seen)
        if pd.isna(value):
            raise ValueError("Formula references a blank or non-numeric cell")
        return str(float(value))

    expression = CELL_REF_RE.sub(replace_cell_reference, expression)

    if re.search(r"[A-Za-z]", expression):
        raise ValueError("Unsupported formula expression")

    return evaluate_math_node(ast.parse(expression, mode="eval"))


def formula_backed_column_values(file_path, sheet_name, header_idx, column_index, row_count):
    workbook = load_workbook(file_path, data_only=False)
    worksheet = workbook[sheet_name]
    values = []

    for row_idx in range(row_count):
        excel_row = header_idx + 2 + row_idx
        cell = worksheet.cell(row=excel_row, column=column_index)

        try:
            value = (
                evaluate_excel_formula(worksheet, cell.value)
                if isinstance(cell.value, str) and cell.value.startswith("=")
                else cell.value
            )
        except ValueError:
            value = None

        values.append(value)

    return pd.Series(pd.to_numeric(values, errors="coerce"))


def empty_transactions():
    return pd.DataFrame(columns=TRANSACTION_COLUMNS)


def read_previous_sheet(file_path, sheet_name, columns):
    if not os.path.exists(file_path):
        return pd.DataFrame(columns=columns)

    try:
        workbook = pd.ExcelFile(file_path)
        if sheet_name not in workbook.sheet_names:
            return pd.DataFrame(columns=columns)

        data = pd.read_excel(file_path, sheet_name=sheet_name)
    except Exception:
        return pd.DataFrame(columns=columns)

    for column in columns:
        if column not in data.columns:
            data[column] = None

    return data[columns].copy()


def build_current_state(holdings):
    state = holdings[STATE_COLUMNS].copy()
    state["Shares"] = pd.to_numeric(state["Shares"], errors="coerce").fillna(0)
    state["Current Price"] = pd.to_numeric(
        state["Current Price"],
        errors="coerce",
    ).fillna(0)
    state["Market Value"] = pd.to_numeric(
        state["Market Value"],
        errors="coerce",
    ).fillna(0)
    return state


def detect_share_transactions(previous_state, current_state):
    if previous_state.empty:
        return pd.DataFrame(columns=TRANSACTION_BASE_COLUMNS)

    previous_state = previous_state.set_index("Asset", drop=False)
    current_state = current_state.set_index("Asset", drop=False)
    transaction_rows = []
    transaction_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    for asset in sorted(set(previous_state.index).union(current_state.index)):
        previous_row = previous_state.loc[asset] if asset in previous_state.index else None
        current_row = current_state.loc[asset] if asset in current_state.index else None

        previous_shares = (
            pd.to_numeric(previous_row["Shares"], errors="coerce")
            if previous_row is not None
            else 0
        )
        current_shares = (
            pd.to_numeric(current_row["Shares"], errors="coerce")
            if current_row is not None
            else 0
        )
        previous_shares = 0 if pd.isna(previous_shares) else previous_shares
        current_shares = 0 if pd.isna(current_shares) else current_shares
        share_change = current_shares - previous_shares

        if abs(share_change) < 0.000001:
            continue

        price_source = current_row if current_row is not None else previous_row
        price = pd.to_numeric(price_source["Current Price"], errors="coerce")
        price = 0 if pd.isna(price) else price

        transaction_rows.append({
            "Date": transaction_date,
            "Asset": asset,
            "Action": "BUY" if share_change > 0 else "SELL",
            "Quantity": abs(share_change),
            "Price": price,
            "Broker": "",
            "Fees": 0,
            "Benefits": "",
        })

    return pd.DataFrame(transaction_rows, columns=TRANSACTION_BASE_COLUMNS)


def calculate_transaction_metrics(transactions, current_state):
    if transactions.empty:
        return empty_transactions()

    transactions = transactions.copy()

    for column in TRANSACTION_BASE_COLUMNS:
        if column not in transactions.columns:
            transactions[column] = "" if column in ["Date", "Asset", "Action", "Broker", "Benefits"] else 0

    current_prices = current_state.set_index("Asset")["Current Price"].to_dict()
    positions = {}
    cost_bases = {}
    calculated_rows = []

    for _, transaction in transactions[TRANSACTION_BASE_COLUMNS].iterrows():
        asset = transaction["Asset"]
        action = str(transaction["Action"]).upper()
        quantity = pd.to_numeric(transaction["Quantity"], errors="coerce")
        price = pd.to_numeric(transaction["Price"], errors="coerce")
        fees = pd.to_numeric(transaction["Fees"], errors="coerce")
        quantity = 0 if pd.isna(quantity) else quantity
        price = 0 if pd.isna(price) else price
        fees = 0 if pd.isna(fees) else fees

        position_quantity = positions.get(asset, 0)
        cost_basis = cost_bases.get(asset, 0)
        average_price = cost_basis / position_quantity if position_quantity else 0
        realized_gain = 0

        if action == "BUY":
            position_quantity += quantity
            cost_basis += (quantity * price) + fees
        elif action == "SELL":
            cost_removed = average_price * min(quantity, position_quantity)
            realized_gain = (quantity * price) - fees - cost_removed
            position_quantity -= quantity
            cost_basis = max(0, cost_basis - cost_removed)

        average_price = cost_basis / position_quantity if position_quantity else 0
        current_price = current_prices.get(asset, price)
        unrealized_gain = (position_quantity * current_price) - cost_basis

        positions[asset] = position_quantity
        cost_bases[asset] = cost_basis

        row = transaction.to_dict()
        row.update({
            "Realized Gain": realized_gain,
            "Unrealized Gain": unrealized_gain,
            "Cost Basis": cost_basis,
            "Average Purchase Price": average_price,
            "Position Quantity": position_quantity,
        })
        calculated_rows.append(row)

    return pd.DataFrame(calculated_rows, columns=TRANSACTION_COLUMNS)


def risk_label_from_score(score):
    if score >= 85:
        return "Low"
    if score >= 70:
        return "Medium"
    return "High"


def format_money(value):
    return f"KES {value:,.2f}"


def add_dynamic_asset_limits(holdings):
    holdings = holdings.copy()
    sector_asset_counts = holdings.groupby("Sector")["Asset"].transform("count")
    holdings["Asset Limit %"] = (
        SECTOR_WEIGHT_LIMIT / sector_asset_counts
    ).clip(upper=SINGLE_ASSET_WEIGHT_LIMIT)
    return holdings


def sell_amount_to_limit(current_value, total_value, limit_percent):
    limit = limit_percent / 100

    if limit >= 1:
        return 0

    return max(0, (current_value - (limit * total_value)) / (1 - limit))


def buy_amount_to_limit(current_value, total_value, limit_percent):
    limit = limit_percent / 100

    if limit <= 0:
        return 0

    return max(0, (current_value / limit) - total_value)


def build_rebalance_plan(holdings, total_value, sector_risk_total):
    risk_pool = holdings[~holdings["Sector"].isin(SECTOR_RISK_EXCLUSIONS)].copy()
    risk_pool = add_dynamic_asset_limits(risk_pool)

    sector_cap_value = (SECTOR_WEIGHT_LIMIT / 100) * total_value
    targets = risk_pool.set_index("Asset")["Market Value"].to_dict()
    asset_caps = (
        risk_pool.set_index("Asset")["Asset Limit %"] / 100 * total_value
    ).to_dict()
    asset_sectors = risk_pool.set_index("Asset")["Sector"].to_dict()

    for asset, cap_value in asset_caps.items():
        targets[asset] = min(targets[asset], cap_value)

    for sector, sector_assets in risk_pool.groupby("Sector")["Asset"]:
        sector_target = sum(targets[asset] for asset in sector_assets)
        if sector_target > sector_cap_value and sector_target > 0:
            scale_factor = sector_cap_value / sector_target
            for asset in sector_assets:
                targets[asset] *= scale_factor

    proceeds = sum(
        max(0, row["Market Value"] - targets[row["Asset"]])
        for _, row in risk_pool.iterrows()
    )
    remaining_cash = proceeds

    sector_targets = {
        sector: sum(targets[asset] for asset in sector_assets)
        for sector, sector_assets in risk_pool.groupby("Sector")["Asset"]
    }

    candidates = risk_pool.sort_values("Asset Allocation %")
    for _, candidate in candidates.iterrows():
        if remaining_cash <= 0:
            break

        asset = candidate["Asset"]
        sector = candidate["Sector"]
        asset_capacity = max(0, asset_caps[asset] - targets[asset])
        sector_capacity = max(0, sector_cap_value - sector_targets.get(sector, 0))
        buy_value = min(remaining_cash, asset_capacity, sector_capacity)

        if buy_value <= 0:
            continue

        targets[asset] += buy_value
        sector_targets[sector] = sector_targets.get(sector, 0) + buy_value
        remaining_cash -= buy_value

    trades = []
    for _, row in risk_pool.iterrows():
        asset = row["Asset"]
        trade_value = targets[asset] - row["Market Value"]

        if abs(trade_value) < 1 or row["Current Price"] <= 0:
            continue

        action = "BUY" if trade_value > 0 else "SELL"
        shares = math.ceil(abs(trade_value) / row["Current Price"])
        estimated_value = shares * row["Current Price"]
        reason = (
            "Redeploy proceeds into an under-limit asset"
            if action == "BUY"
            else "Reduce asset/sector concentration"
        )

        trades.append({
            "Action": action,
            "Asset": asset,
            "Sector": row["Sector"],
            "Shares": shares,
            "Current Price": row["Current Price"],
            "Estimated Value": estimated_value,
            "Reason": reason,
        })

    if remaining_cash > 1:
        cash_assets = holdings[
            holdings["Sector"].eq("Cash") & (holdings["Current Price"] > 0)
        ].copy()

        if not cash_assets.empty:
            cash_asset = cash_assets.iloc[0]
            shares = math.ceil(remaining_cash / cash_asset["Current Price"])
            trades.append({
                "Action": "BUY",
                "Asset": cash_asset["Asset"],
                "Sector": cash_asset["Sector"],
                "Shares": shares,
                "Current Price": cash_asset["Current Price"],
                "Estimated Value": shares * cash_asset["Current Price"],
                "Reason": "Hold remaining proceeds without adding concentration risk",
            })

    return pd.DataFrame(
        trades,
        columns=[
            "Action",
            "Asset",
            "Sector",
            "Shares",
            "Current Price",
            "Estimated Value",
            "Reason",
        ],
    )


def build_risk_engine(holdings, sector_risk_alloc_pct, total_value, sector_risk_total):
    asset_risk_pool = holdings[~holdings["Sector"].isin(SECTOR_RISK_EXCLUSIONS)].copy()
    asset_risk_pool = add_dynamic_asset_limits(asset_risk_pool)
    asset_violations = asset_risk_pool[
        asset_risk_pool["Asset Allocation %"] > asset_risk_pool["Asset Limit %"]
    ][["Asset", "Sector", "Market Value", "Asset Allocation %", "Asset Limit %"]].copy()
    asset_violations["Excess %"] = (
        asset_violations["Asset Allocation %"] - asset_violations["Asset Limit %"]
    )
    asset_violations = asset_violations[
        [
            "Asset",
            "Sector",
            "Asset Allocation %",
            "Asset Limit %",
            "Excess %",
        ]
    ]

    sector_violations = sector_risk_alloc_pct[
        sector_risk_alloc_pct > SECTOR_WEIGHT_LIMIT
    ].reset_index()
    sector_violations.columns = ["Sector", "Sector Weight %"]
    sector_violations["Sector Value"] = (
        sector_violations["Sector Weight %"] / 100
    ) * total_value
    sector_violations["Limit %"] = SECTOR_WEIGHT_LIMIT
    sector_violations["Excess %"] = (
        sector_violations["Sector Weight %"] - SECTOR_WEIGHT_LIMIT
    )
    sector_violations = sector_violations[
        [
            "Sector",
            "Sector Weight %",
            "Limit %",
            "Excess %",
        ]
    ]

    diversification_score = max(
        0,
        100 - (len(asset_violations) * 3) - (len(sector_violations) * 3),
    )
    risk_score = risk_label_from_score(diversification_score)

    risk_summary = pd.DataFrame({
        "Metric": [
            "Asset Limit",
            "Sector Limit",
            "Single-Asset Cap",
            "Asset Violations",
            "Sector Violations",
            "Diversification Score",
            "Risk Score",
        ],
        "Value": [
            "Sector limit / asset count",
            f"{SECTOR_WEIGHT_LIMIT}%",
            f"{SINGLE_ASSET_WEIGHT_LIMIT}%",
            len(asset_violations),
            len(sector_violations),
            f"{diversification_score} / 100",
            risk_score,
        ],
    })

    return risk_summary, asset_violations, sector_violations


def style_dashboard_sheet(
    worksheet,
    asset_count,
    sector_count,
    risk_summary_count,
    asset_violation_count,
    sector_violation_count,
    suggestion_count,
):
    thin_border = Border(
        left=Side(style="thin", color=BORDER_COLOR),
        right=Side(style="thin", color=BORDER_COLOR),
        top=Side(style="thin", color=BORDER_COLOR),
        bottom=Side(style="thin", color=BORDER_COLOR),
    )
    title_fill = PatternFill("solid", fgColor=DARK_OLIVE)
    header_fill = PatternFill("solid", fgColor=DARK_OLIVE)
    odd_fill = PatternFill("solid", fgColor=WARM_BEIGE)
    even_fill = PatternFill("solid", fgColor=WARM_WHITE)
    summary_fill = PatternFill("solid", fgColor=SOFT_BEIGE)

    worksheet.sheet_view.showGridLines = False
    worksheet.freeze_panes = None
    worksheet.merge_cells("A1:C1")
    worksheet["A1"] = "Portfolio Dashboard"
    worksheet["A1"].fill = title_fill
    worksheet["A1"].font = Font(name="Georgia", color=CREAM, bold=True, size=16)
    worksheet["A1"].alignment = Alignment(horizontal="center", vertical="center")
    worksheet.row_dimensions[1].height = 25

    widths = {
        "A": 28,
        "B": 18,
        "C": 22,
        "D": 14,
        "E": 28,
        "F": 18,
        "G": 22,
        "H": 42,
        "I": 18,
        "J": 18,
    }
    for column, width in widths.items():
        worksheet.column_dimensions[column].width = width

    table_ranges = [
        (SUMMARY_START_ROW + 1, SUMMARY_START_ROW + 1 + 3, 2),
        (ASSET_TABLE_START_ROW + 1, ASSET_TABLE_START_ROW + 1 + asset_count, 3),
        (
            ASSET_TABLE_START_ROW + asset_count + 4,
            ASSET_TABLE_START_ROW + asset_count + 4 + sector_count,
            2,
        ),
        (
            ASSET_TABLE_START_ROW + asset_count + sector_count + 7,
            ASSET_TABLE_START_ROW + asset_count + sector_count + 7 + risk_summary_count,
            2,
        ),
        (
            ASSET_TABLE_START_ROW + asset_count + sector_count + risk_summary_count + 10,
            ASSET_TABLE_START_ROW + asset_count + sector_count + risk_summary_count + 10 + asset_violation_count,
            5,
        ),
        (
            ASSET_TABLE_START_ROW + asset_count + sector_count + risk_summary_count + asset_violation_count + 13,
            ASSET_TABLE_START_ROW + asset_count + sector_count + risk_summary_count + asset_violation_count + 13 + sector_violation_count,
            4,
        ),
        (
            ASSET_TABLE_START_ROW + asset_count + sector_count + risk_summary_count + asset_violation_count + sector_violation_count + 16,
            ASSET_TABLE_START_ROW + asset_count + sector_count + risk_summary_count + asset_violation_count + sector_violation_count + 16 + suggestion_count,
            7,
        ),
    ]

    for start_row, end_row, end_col in table_ranges:
        for row in range(start_row, end_row + 1):
            is_header = row == start_row
            fill = header_fill if is_header else odd_fill if row % 2 == 0 else even_fill
            font = (
                Font(name="Georgia", color=CREAM, bold=True)
                if is_header
                else Font(name="Georgia", color=TEXT_DARK)
            )

            for col in range(1, end_col + 1):
                cell = worksheet.cell(row=row, column=col)
                cell.fill = fill
                cell.font = font
                cell.border = thin_border
                cell.alignment = Alignment(
                    horizontal="left" if col == 1 else "center",
                    vertical="center",
                    wrap_text=col >= 7,
                )

    for row in range(SUMMARY_START_ROW + 2, SUMMARY_START_ROW + 5):
        for col in range(1, 3):
            worksheet.cell(row=row, column=col).fill = summary_fill

    for row in range(ASSET_TABLE_START_ROW + 2, ASSET_TABLE_START_ROW + 2 + asset_count):
        worksheet.cell(row=row, column=2).number_format = '#,##0.00'
        worksheet.cell(row=row, column=3).number_format = '0.00"%"'

    sector_header_row = ASSET_TABLE_START_ROW + asset_count + 4
    for row in range(sector_header_row + 1, sector_header_row + 1 + sector_count):
        worksheet.cell(row=row, column=2).number_format = '0.00"%"'

    risk_summary_header_row = ASSET_TABLE_START_ROW + asset_count + sector_count + 7
    asset_risk_header_row = risk_summary_header_row + risk_summary_count + 3
    sector_risk_header_row = asset_risk_header_row + asset_violation_count + 3
    suggestion_header_row = sector_risk_header_row + sector_violation_count + 3
    suggestion_title_row = suggestion_header_row - 1

    worksheet.merge_cells(
        start_row=suggestion_title_row,
        start_column=1,
        end_row=suggestion_title_row,
        end_column=7,
    )
    suggestion_title = worksheet.cell(row=suggestion_title_row, column=1)
    suggestion_title.value = "Holistic Rebalance Suggestion"
    suggestion_title.fill = title_fill
    suggestion_title.font = Font(name="Georgia", color=CREAM, bold=True, size=12)
    suggestion_title.alignment = Alignment(horizontal="center", vertical="center")
    worksheet.row_dimensions[suggestion_title_row].height = 22

    for row in range(asset_risk_header_row + 1, asset_risk_header_row + 1 + asset_violation_count):
        worksheet.cell(row=row, column=3).number_format = '0.00"%"'
        worksheet.cell(row=row, column=4).number_format = '0.00"%"'
        worksheet.cell(row=row, column=5).number_format = '0.00"%"'

    for row in range(sector_risk_header_row + 1, sector_risk_header_row + 1 + sector_violation_count):
        worksheet.cell(row=row, column=2).number_format = '0.00"%"'
        worksheet.cell(row=row, column=3).number_format = '0.00"%"'
        worksheet.cell(row=row, column=4).number_format = '0.00"%"'

    for row in range(suggestion_header_row + 1, suggestion_header_row + 1 + suggestion_count):
        worksheet.cell(row=row, column=4).number_format = '#,##0'
        worksheet.cell(row=row, column=5).number_format = '#,##0.00'
        worksheet.cell(row=row, column=6).number_format = '#,##0.00'

    for row in range(1, worksheet.max_row + 1):
        worksheet.row_dimensions[row].height = 18
    worksheet.row_dimensions[1].height = 25

    for row in range(suggestion_header_row + 1, suggestion_header_row + suggestion_count + 1):
        worksheet.row_dimensions[row].height = 36


def add_dashboard_charts(
    file_path,
    asset_count,
    sector_count,
    risk_summary_count,
    asset_violation_count,
    sector_violation_count,
    suggestion_count,
):
    workbook = load_workbook(file_path)
    worksheet = workbook["Dashboard1"]
    style_dashboard_sheet(
        worksheet,
        asset_count,
        sector_count,
        risk_summary_count,
        asset_violation_count,
        sector_violation_count,
        suggestion_count,
    )

    asset_header_row = ASSET_TABLE_START_ROW + 1
    asset_first_row = asset_header_row + 1
    asset_last_row = asset_header_row + asset_count

    sector_header_row = ASSET_TABLE_START_ROW + asset_count + 4
    sector_first_row = sector_header_row + 1
    sector_last_row = sector_header_row + sector_count

    if asset_count:
        pie_chart = PieChart()
        pie_chart.title = "Asset Allocation"
        pie_chart.height = 9
        pie_chart.width = 13

        pie_data = Reference(
            worksheet,
            min_col=3,
            min_row=asset_header_row,
            max_row=asset_last_row,
        )
        pie_labels = Reference(
            worksheet,
            min_col=1,
            min_row=asset_first_row,
            max_row=asset_last_row,
        )

        pie_chart.add_data(pie_data, titles_from_data=True)
        pie_chart.set_categories(pie_labels)
        worksheet.add_chart(pie_chart, "E2")

    if sector_count:
        bar_chart = BarChart()
        bar_chart.title = "Sector Allocation"
        bar_chart.y_axis.title = "Allocation %"
        bar_chart.x_axis.title = "Sector"
        bar_chart.height = 9
        bar_chart.width = 13

        bar_data = Reference(
            worksheet,
            min_col=2,
            min_row=sector_header_row,
            max_row=sector_last_row,
        )
        bar_categories = Reference(
            worksheet,
            min_col=1,
            min_row=sector_first_row,
            max_row=sector_last_row,
        )

        bar_chart.add_data(bar_data, titles_from_data=True)
        bar_chart.set_categories(bar_categories)
        worksheet.add_chart(bar_chart, "E20")

    workbook.save(file_path)

# -----------------------------
# FILES
# -----------------------------
input_file = "Portfolio_Tracker_Kenya.xlsx"
output_file = "Portfolio_Dashboard_Output.xlsx"

backup_path = f"backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
shutil.copy(input_file, backup_path)

print(f"Backup created: {backup_path}")

# -----------------------------
# READ RAW EXCEL
# -----------------------------
holdings_raw = pd.read_excel(input_file, sheet_name="Holdings", header=None)

# Find header row dynamically
header_idx = None

for i in range(len(holdings_raw)):
    row = holdings_raw.iloc[i].astype(str).str.lower()
    if "asset" in row.values and "sector" in row.values:
        header_idx = i
        break

if header_idx is None:
    raise ValueError("Could not find header row in Holdings sheet")

# Re-read properly
holdings = pd.read_excel(input_file, sheet_name="Holdings", header=header_idx)
holdings.columns = holdings.columns.astype(str).str.strip()

# -----------------------------
# CRITICAL FIX 1: FORCE NUMERIC CLEANING
# -----------------------------
for col in ["Shares", "Current Price"]:
    if col not in holdings.columns:
        holdings[col] = 0

    numeric_values = pd.to_numeric(holdings[col], errors="coerce")

    if col == "Current Price":
        formula_values = formula_backed_column_values(
            input_file,
            "Holdings",
            header_idx,
            holdings.columns.get_loc(col) + 1,
            len(holdings),
        )
        holdings[col] = numeric_values.fillna(formula_values).fillna(0)
    else:
        holdings[col] = numeric_values.fillna(0)

# Gain/Loss safety
if "Gain/Loss" in holdings.columns:
    holdings["Gain/Loss"] = pd.to_numeric(holdings["Gain/Loss"], errors="coerce").fillna(0)
else:
    holdings["Gain/Loss"] = 0

current_sector = None
for row_index, asset_name in holdings["Asset"].items():
    if asset_name in SECTOR_LABELS:
        current_sector = SECTOR_LABELS[asset_name]
    elif pd.notna(asset_name) and pd.isna(holdings.at[row_index, "Sector"]):
        holdings.at[row_index, "Sector"] = current_sector

# -----------------------------
# CLEAN DATA (safe filtering)
# -----------------------------
invalid_labels = list(SECTOR_LABELS.keys()) + [
    "Sector Value", "Cash", "Total Portfolio Value"
]

holdings = holdings[holdings["Asset"].notna()]
holdings = holdings[~holdings["Asset"].isin(invalid_labels)]
holdings = holdings.copy()

# -----------------------------
# CRITICAL FIX 2: COMPUTE MARKET VALUE SAFELY
# -----------------------------
holdings["Market Value"] = holdings["Shares"] * holdings["Current Price"]

print("\n--- CLEAN HOLDINGS SAMPLE ---")
print(holdings[["Asset", "Shares", "Current Price", "Market Value"]].head(15))

# -----------------------------
# TOTAL VALUE
# -----------------------------
total_value = holdings["Market Value"].sum()

print("\nTOTAL PORTFOLIO VALUE:", total_value)

# Avoid division by zero crash
if total_value == 0:
    holdings["Asset Allocation %"] = 0
else:
    holdings["Asset Allocation %"] = (holdings["Market Value"] / total_value) * 100

print("\n--- CLEAN ASSET ALLOCATION ---")
print(holdings[["Asset", "Market Value", "Asset Allocation %"]])

# -----------------------------
# SECTOR ALLOCATION
# -----------------------------
if "Sector" not in holdings.columns:
    holdings["Sector"] = "Unknown"

sector_alloc = holdings.groupby("Sector")["Market Value"].sum()

if total_value == 0:
    sector_alloc_pct = sector_alloc * 0
else:
    sector_alloc_pct = (sector_alloc / total_value) * 100

print("\n--- CLEAN SECTOR ALLOCATION ---")
print(sector_alloc_pct)

# -----------------------------
# PHASE 2 RISK ENGINE
# -----------------------------
sector_risk_pool = holdings[~holdings["Sector"].isin(SECTOR_RISK_EXCLUSIONS)].copy()
sector_risk_alloc = sector_risk_pool.groupby("Sector")["Market Value"].sum()
sector_risk_total = sector_risk_alloc.sum()

if sector_risk_total == 0:
    sector_risk_alloc_pct = sector_risk_alloc * 0
else:
    sector_risk_alloc_pct = (sector_risk_alloc / total_value) * 100

risk_summary, asset_violations, sector_violations = build_risk_engine(
    holdings,
    sector_risk_alloc_pct,
    total_value,
    sector_risk_total,
)
rebalance_plan = build_rebalance_plan(holdings, total_value, sector_risk_total)

print("\n--- RISK CHECK (DYNAMIC ASSET RULE) ---")

if asset_violations.empty:
    print("No asset concentration violations.")
else:
    print(asset_violations)

print(f"\n--- RISK CHECK ({SECTOR_WEIGHT_LIMIT}% SECTOR RULE) ---")

if sector_violations.empty:
    print("No sector concentration violations.")
else:
    print(sector_violations)

print("\n--- RISK SCORE ---")
print(risk_summary)

print("\n--- HOLISTIC REBALANCE SUGGESTION ---")
if rebalance_plan.empty:
    print("No trades needed.")
else:
    print(rebalance_plan)

# -----------------------------
# PLOTS (SAFE GUARDS FIX)
# -----------------------------
plt.figure()

plot_data = holdings.copy()
plot_data = plot_data.dropna(subset=["Market Value", "Asset Allocation %"])
plot_data = plot_data[plot_data["Market Value"] > 0]

if not plot_data.empty:
    plot_data.set_index("Asset")["Asset Allocation %"].plot(kind="pie", autopct="%1.1f%%")
else:
    print("No valid data for pie chart.")

plt.ylabel("")
plt.show()

plt.figure()

if not sector_alloc_pct.dropna().empty:
    sector_alloc_pct.plot(kind="bar")
    plt.title("Sector Allocation")
    plt.ylabel("Percentage")
    plt.xticks(rotation=45)
    plt.tight_layout()
else:
    print("No valid sector data to plot.")

plt.show()

# -----------------------------
# DASHBOARD EXPORT (FIXED)
# -----------------------------
summary_df = pd.DataFrame({
    "Metric": [
        "Total Portfolio Value",
        "Number of Assets",
        "Number of Sectors"
    ],
    "Value": [
        total_value,
        len(holdings),
        holdings["Sector"].nunique()
    ]
})

asset_table = holdings[["Asset", "Market Value", "Asset Allocation %"]]
sector_table = sector_alloc_pct.reset_index()
sector_table.columns = ["Sector", "Allocation %"]
risk_summary_startrow = ASSET_TABLE_START_ROW + len(asset_table) + len(sector_table) + 6
asset_violations_startrow = risk_summary_startrow + len(risk_summary) + 3
sector_violations_startrow = asset_violations_startrow + len(asset_violations) + 3
rebalance_plan_startrow = sector_violations_startrow + len(sector_violations) + 3

with pd.ExcelWriter(output_file, engine="openpyxl", mode="w") as writer:
    summary_df.to_excel(
        writer,
        sheet_name="Dashboard1",
        startrow=SUMMARY_START_ROW,
        index=False,
    )
    asset_table.to_excel(
        writer,
        sheet_name="Dashboard1",
        startrow=ASSET_TABLE_START_ROW,
        index=False,
    )
    sector_table.to_excel(
        writer,
        sheet_name="Dashboard1",
        startrow=ASSET_TABLE_START_ROW + len(asset_table) + 3,
        index=False,
    )
    risk_summary.to_excel(
        writer,
        sheet_name="Dashboard1",
        startrow=risk_summary_startrow,
        index=False,
    )
    asset_violations.to_excel(
        writer,
        sheet_name="Dashboard1",
        startrow=asset_violations_startrow,
        index=False,
    )
    sector_violations.to_excel(
        writer,
        sheet_name="Dashboard1",
        startrow=sector_violations_startrow,
        index=False,
    )
    rebalance_plan.to_excel(
        writer,
        sheet_name="Dashboard1",
        startrow=rebalance_plan_startrow,
        index=False,
    )

add_dashboard_charts(
    output_file,
    len(asset_table),
    len(sector_table),
    len(risk_summary),
    len(asset_violations),
    len(sector_violations),
    len(rebalance_plan),
)

print("\nDashboard Generated Successfully.")
