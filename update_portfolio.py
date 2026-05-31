import os
import shutil
import ast
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


def suggested_buy_assets(holdings, excluded_asset=None, excluded_sector=None):
    candidates = holdings[
        (holdings["Asset"] != excluded_asset)
        & (holdings["Asset Allocation %"] < holdings["Asset Limit %"])
        & (~holdings["Sector"].isin(SECTOR_RISK_EXCLUSIONS))
    ].copy()

    if excluded_sector is not None:
        candidates = candidates[candidates["Sector"] != excluded_sector]

    candidates = candidates.sort_values("Asset Allocation %")
    return ", ".join(candidates["Asset"].head(3))


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


def build_risk_engine(holdings, sector_risk_alloc_pct, total_value, sector_risk_total):
    asset_risk_pool = holdings[~holdings["Sector"].isin(SECTOR_RISK_EXCLUSIONS)].copy()
    asset_risk_pool = add_dynamic_asset_limits(asset_risk_pool)
    asset_violations = asset_risk_pool[
        asset_risk_pool["Asset Allocation %"] > asset_risk_pool["Asset Limit %"]
    ][["Asset", "Sector", "Market Value", "Asset Allocation %", "Asset Limit %"]].copy()
    asset_violations["Excess %"] = (
        asset_violations["Asset Allocation %"] - asset_violations["Asset Limit %"]
    )
    asset_violations["Sell To Fix"] = asset_violations.apply(
        lambda row: format_money(
            sell_amount_to_limit(row["Market Value"], total_value, row["Asset Limit %"])
        ),
        axis=1,
    )
    asset_violations["Buy Elsewhere To Fix"] = asset_violations.apply(
        lambda row: format_money(
            buy_amount_to_limit(row["Market Value"], total_value, row["Asset Limit %"])
        ),
        axis=1,
    )
    asset_violations["Buy Candidates"] = asset_violations.apply(
        lambda row: suggested_buy_assets(
            asset_risk_pool,
            excluded_asset=row["Asset"],
            excluded_sector=row["Sector"],
        ),
        axis=1,
    )
    asset_violations["Suggested Fix"] = asset_violations.apply(
        lambda row: (
            f"Sell {row['Sell To Fix']} of {row['Asset']} or buy "
            f"{row['Buy Elsewhere To Fix']} across {row['Buy Candidates']}."
        ),
        axis=1,
    )
    asset_violations = asset_violations[
        [
            "Asset",
            "Sector",
            "Asset Allocation %",
            "Asset Limit %",
            "Excess %",
            "Sell To Fix",
            "Buy Elsewhere To Fix",
            "Buy Candidates",
            "Suggested Fix",
        ]
    ]

    sector_violations = sector_risk_alloc_pct[
        sector_risk_alloc_pct > SECTOR_WEIGHT_LIMIT
    ].reset_index()
    sector_violations.columns = ["Sector", "Sector Weight %"]
    sector_violations["Sector Value"] = (
        sector_violations["Sector Weight %"] / 100
    ) * sector_risk_total
    sector_violations["Limit %"] = SECTOR_WEIGHT_LIMIT
    sector_violations["Excess %"] = (
        sector_violations["Sector Weight %"] - SECTOR_WEIGHT_LIMIT
    )
    sector_violations["Sell From Sector"] = sector_violations["Sector Value"].apply(
        lambda value: format_money(sell_amount_to_limit(value, sector_risk_total, SECTOR_WEIGHT_LIMIT))
    )
    sector_violations["Buy Outside Sector"] = sector_violations["Sector Value"].apply(
        lambda value: format_money(buy_amount_to_limit(value, sector_risk_total, SECTOR_WEIGHT_LIMIT))
    )
    sector_violations["Buy Candidates"] = sector_violations["Sector"].apply(
        lambda sector: suggested_buy_assets(asset_risk_pool, excluded_sector=sector)
    )
    sector_violations["Suggested Fix"] = sector_violations.apply(
        lambda row: (
            f"Sell {row['Sell From Sector']} from {row['Sector']} or buy "
            f"{row['Buy Outside Sector']} across {row['Buy Candidates']}."
        ),
        axis=1,
    )
    sector_violations = sector_violations[
        [
            "Sector",
            "Sector Weight %",
            "Limit %",
            "Excess %",
            "Sell From Sector",
            "Buy Outside Sector",
            "Buy Candidates",
            "Suggested Fix",
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
        "H": 65,
        "I": 65,
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
            9,
        ),
        (
            ASSET_TABLE_START_ROW + asset_count + sector_count + risk_summary_count + asset_violation_count + 13,
            ASSET_TABLE_START_ROW + asset_count + sector_count + risk_summary_count + asset_violation_count + 13 + sector_violation_count,
            8,
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
                    wrap_text=col >= 8,
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

    for row in range(asset_risk_header_row + 1, asset_risk_header_row + 1 + asset_violation_count):
        worksheet.cell(row=row, column=3).number_format = '0.00"%"'
        worksheet.cell(row=row, column=4).number_format = '0.00"%"'
        worksheet.cell(row=row, column=5).number_format = '0.00"%"'

    for row in range(sector_risk_header_row + 1, sector_risk_header_row + 1 + sector_violation_count):
        worksheet.cell(row=row, column=2).number_format = '0.00"%"'
        worksheet.cell(row=row, column=3).number_format = '0.00"%"'
        worksheet.cell(row=row, column=4).number_format = '0.00"%"'

    for row in range(1, worksheet.max_row + 1):
        worksheet.row_dimensions[row].height = 18
    worksheet.row_dimensions[1].height = 25

    for row in range(asset_risk_header_row + 1, sector_risk_header_row + sector_violation_count + 1):
        worksheet.row_dimensions[row].height = 36


def add_dashboard_charts(
    file_path,
    asset_count,
    sector_count,
    risk_summary_count,
    asset_violation_count,
    sector_violation_count,
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
    sector_risk_alloc_pct = (sector_risk_alloc / sector_risk_total) * 100

risk_summary, asset_violations, sector_violations = build_risk_engine(
    holdings,
    sector_risk_alloc_pct,
    total_value,
    sector_risk_total,
)

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

add_dashboard_charts(
    output_file,
    len(asset_table),
    len(sector_table),
    len(risk_summary),
    len(asset_violations),
    len(sector_violations),
)

print("\nDashboard Generated Successfully.")
