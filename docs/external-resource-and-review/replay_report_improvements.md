# Replay Report Improvements

## Objective
Transform the replay report from descriptive (what happened) to diagnostic (why it worked, whether it is robust, and whether it is implementable).

---

## 1. Decision Funnel (Critical)
Track candidate flow through the full pipeline:

- Universe → Valid groups → Eligible members → Rank filter → Signal trigger → Entry filters → Executed trades

**Metrics:**
- Counts, pass rates
- Expectancy at each stage

**Purpose:** Identify which filters create or destroy edge.

---

## 2. Cost & Execution Realism (Critical)
Add per-trade and aggregate:

- Gross vs net PnL
- Fees, taxes, slippage
- Entry/exit slippage vs decision price
- % ADV consumed

Include **sensitivity analysis** under multiple cost assumptions.

**Purpose:** Ensure alpha survives realistic frictions.

---

## 3. Trade Path Decomposition (Critical)
For each trade:

- MAE / MFE
- Time to TP
- Slice-level PnL (partial exits vs residual)
- Peak/trough unrealized PnL

**Purpose:** Detect path dependence and whether profits come from tail events.

---

## 4. Opportunity & Filter Attribution (Critical)
For all blocked/timed-out signals:

- Shadow returns (5m, 15m, close)
- MFE / MAE
- Block reason

**Output:** Expectancy by filter

**Purpose:** Validate whether filters add value or reduce opportunity.

---

## 5. Statistical Robustness
Add beyond basic metrics:

- Median PnL, std dev
- Expectancy (per trade, bps)
- Payoff ratio
- Skew, kurtosis
- Bootstrap CI (mean return, profit factor)

**Purpose:** Quantify uncertainty and avoid overinterpretation.

---

## 6. Concentration Analysis

- PnL by top dates, symbols, groups
- Contribution of top 1%, 5%, 10% trades
- PnL excluding top contributors

**Purpose:** Detect dependence on few events or names.

---

## 7. Regime Conditioning
Segment performance by:

- Market state (e.g., index return, volatility)
- Time-of-entry buckets
- Breadth / group strength

**Purpose:** Identify hidden beta and regime dependence.

---

## 8. Portfolio-Level Risk
Add daily-level reporting:

- Equity curve, drawdowns, recovery time
- Rolling metrics (hit rate, expectancy)
- Capital utilization, turnover
- Concurrent positions

**Purpose:** Capture path risk and capital efficiency.

---

## 9. Edge Attribution Decomposition
Report performance for:

- Raw signal
- Signal + screen
- Signal + filters
- Full strategy (gross & net)

**Purpose:** Separate true edge from filtering artifacts.

---

## 10. Parameter Sensitivity
Local perturbation of key thresholds:

- Entry conditions
- Stops, TP levels
- Time windows

**Purpose:** Detect overfitting (non-smooth performance).

---

## Recommended New Outputs

- `report_funnel.csv`
- `report_trade_paths.csv`
- `report_daily.csv`
- `report_regime.csv`
- `report_filter_effect.csv`
- `report_concentration.csv`
- `report_sensitivity.csv`

---

## Priority (If Limited Resources)
1. Funnel
2. Costs & slippage
3. Trade path (MAE/MFE, slices)
4. Filter attribution (shadow analysis)
5. Daily/regime reporting

---

## Bottom Line

A valid replay report must:
- Attribute edge
- Quantify uncertainty
- Test robustness
- Reflect real execution

Without these, reported performance is not reliable evidence of tradable alpha.