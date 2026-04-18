# Day High Breakout 策略規格書

## 1. 策略總覽

### 1.1 策略名稱
Day High Breakout（盤中新高突破）

### 1.2 策略類型
盤中動量追蹤，日內交易為主，漲停時留倉至隔天

### 1.3 核心邏輯
在強勢族群中找到當天漲幅最大的個股，等它從 day high 拉回後再次突破時進場。利用 breakout 的動能持有到收盤，漲停時留倉捕捉隔天跳空利潤。

### 1.4 Alpha 來源
- Day high breakout = 盤中最強的多方確認信號（所有持有者都獲利，賣壓消化完畢）
- Pullback 要求確保不是開盤噴單的噪音，而是經過洗盤後的真突破
- 限制在高位階（>=6%）確保離漲停近，漲停留倉的機率大幅提升

---

## 2. 交易標的篩選

### 2.1 股票池（Universe）
- 台股上市（TSE）+ 上櫃（OTC）個股
- 排除 ETF（00 開頭）
- 排除處置股（disposition stocks）

### 2.2 族群篩選（Strong Group）
| 條件 | 參數 | 說明 |
|---|---|---|
| 個股月均成交值 | >= 2 億 | 流動性門檻 |
| 族群月均成交值 | >= 30 億 | 族群流動性 |
| 族群當日平均漲幅 | > 1% | 族群有動能 |
| 族群成交值比 | >= 1 | 今天有量 |
| 族群排名 | 前 10 名（G1-10）| 只做最強族群 |

### 2.3 個股排名
| 條件 | 參數 | 說明 |
|---|---|---|
| 族群內排名 | VWAP% Rank 1（M1）| 族群中 VWAP 漲幅最大的那檔 |
| Raw rank 也要 #1 | require_raw_m1 = true | 不只在篩過的排名，在最寬排名也要第一 |

---

## 3. 進場條件

### 3.1 訊號定義（Day High Breakout）

**狀態機：**
```
Step 1: 追蹤股票的盤中 day high（established_high）
Step 2: 價格從 day high 拉回 >= 1%（pullback confirmed）
Step 3: 價格再次 > established_high → 觸發進場
Step 4: 如果在 pullback 確認前出現新的 day high → 重設到 Step 1
```

**每檔每天只觸發一次（single-fire）**

### 3.2 進場濾網

| 條件 | 參數 | 邏輯 |
|---|---|---|
| 進場時段 | 09:05 ~ 10:00 | 開盤 5 分鐘後才進場（排除開盤噪音）；10:00 後動能消退 |
| 進場位階下限 | >= 6%（from prev close）| 離漲停近、動能足 |
| 進場位階上限 | < 9.5% | screening 層的 VWAP% 上限 |
| 族群漲停數 | < 2 | 族群內已有 2+ 檔漲停時不進場（追尾效應）|
| 處置股 | 排除 | disposition_stocks_enabled + block_disposition_entry |
| 已持有 | 不重複進場 | already_holding check |

### 3.3 進場價格
- 使用 ask[0].price（最佳委賣價）
- 如果 ask 為 0 則用 match price

### 3.4 部位大小
- 固定 1000 萬 / 筆
- position_scale_nth = 1.0（不隨筆數縮放）

---

## 4. 出場規則

### 4.1 優先順序
```
1. 停損（stop-loss）
2. 時間出場 / 漲停留倉（time exit / hold overnight）
3. 停利（take profit）— 目前未啟用
4. Bailout — 目前未啟用
```

### 4.2 停損
| 參數 | 值 | 說明 |
|---|---|---|
| 模式 | VWAP 停損 | 跌破 VWAP = 趨勢失效 |
| 比率 | VWAP × 0.990 | 給 1% 的緩衝空間 |
| 執行 | 用 bid price 賣出 | 停損用市價（bid）|

**Plateau 驗證：0.989 ~ 0.992 之間報酬穩定（±0.01%），不是 overfitting**

### 4.3 時間出場
| 參數 | 值 |
|---|---|
| 出場時間 | 13:20 |
| 執行 | 用 bid price 賣出 |

### 4.4 漲停留倉
| 條件 | 行為 |
|---|---|
| 13:20 時漲停鎖死 + SignalDayHigh | 不平倉，建立 OvernightHolding |
| 隔天（batch mode） | 第一筆成交賣出 |
| 隔天稅率 | 0.3%（vs 當沖 0.15%） |

### 4.5 未啟用的出場
| 方式 | 狀態 | 原因 |
|---|---|---|
| 停利（take profit）| 關閉 | 策略核心利潤來自漲停，提早停利會砍掉利潤 |
| Trailing stop | 關閉 | 實測與模擬差距巨大（模擬 +1.38%，實際 -0.05%）|
| Bailout | 關閉 | |

---

## 5. 成本模型

| 項目 | 值 |
|---|---|
| 手續費 | 0.1425% × 1.2 折 = 0.0171% / 單邊 |
| 當沖交易稅 | 0.15%（賣出） |
| 留倉交易稅 | 0.30%（賣出） |
| 滑價 | 5 bps / 單邊 |
| 每筆加權平均成本 | ~0.35% |

---

## 6. 資料需求

### 6.1 行情資料
| 檔案 | 格式 | 說明 |
|---|---|---|
| TSEQuote.YYYYMMDD | Raw text | 上市逐筆成交 + 五檔 |
| OTCQuote.YYYYMMDD | Raw text | 上櫃逐筆成交 + 五檔 |

### 6.2 參考資料
| 檔案 | 說明 |
|---|---|
| Symbols_YYYYMMDD.csv | 前收價、漲跌停價、處置股標記 |
| group.csv | 族群成員定義 |

### 6.3 歷史資料
- 回測當天的前 20 個交易日（history window）
- 用於計算月均成交值、月均成交量

---

## 7. 因子研究摘要

### 7.1 基礎因子（定義策略本質）
| 因子 | 結論 | 驗證方式 |
|---|---|---|
| 進場位階 >= 6% | 6-8% 一致正報酬，<4% 一致虧 | 單因子分析，5 個月穩定 |
| M1 排名 | M1 勝率和留倉率顯著高於 M2+ | 單因子分析 + 控制位階後邊際貢獻 |
| Pullback 1% | 0.5-1.0% 完全相同（不敏感）| Plateau test |
| VWAP × 0.990 停損 | 0.989-0.992 plateau | 參數掃描 |

### 7.2 濾網（排除極端值）
| 因子 | 結論 | 驗證方式 |
|---|---|---|
| 09:05 開始 | 排除後穩定性從 3/4 → 4/4 月正 | 1 分鐘級別時段分析 |
| 10:00 結束 | 10:00 後 MFE 下降、穩定性差 | 時段分析 |
| GLU < 2 | GLU 2+ 一致虧損（0/4 穩定）| 單因子分析 |

### 7.3 進階因子（有獨立邊際貢獻）
| 因子 | 結論 | 驗證方式 |
|---|---|---|
| Group Rank G1-10 | 控制位階後仍單調，Sharpe 提升 0.061 | 相關性分析 + 控制變量分析 |

### 7.4 否決的因子
| 因子 | 結論 | 原因 |
|---|---|---|
| VWAP 乖離 | 控制位階後反向 | 偽因子 |
| 量比（VR） | 方向不一致 | 兩個位階桶內方向相反 |
| 超額漲幅（位階-大盤） | 12 月不穩定 | 跟位階共線性 r=0.67 |
| 月均成交值 | 不單調 | 無交易邏輯 |
| Pullback 幅度 | 方向不一致 | |
| Trailing stop | 模擬 vs 實際差距巨大 | tick 滑價 |

---

## 8. 已知限制

1. **資料長度**：目前只有 ~80 天回測，統計顯著性有限
2. **動量策略固有風險**：弱市時族群動能不足，策略自然減少交易但仍可能微虧
3. **留倉集中度**：44% 的交易走到漲停留倉，如果同時多檔留倉隔天跳空低開，單日虧損大
4. **成本敏感**：Gross 和 Net 差 ~0.35%，手續費折扣是關鍵
5. **holdOvernight bug**：已修復（position 在 tick loop 中未正確清除，導致重複觸發）

---

## 9. Config 參考

```ini
[SignalDayHigh]
enabled=true
entry_start_time=90500000000
entry_end_time=100000000000
min_increase_ratio=0.06
max_increase_ratio=0.095
pullback_ratio=0.01
max_entries_per_symbol=1
max_group_limit_up_count=2

[StrongGroup]
group_valid_top_n=10
top_group_max_select=1
normal_group_max_select=1
require_raw_m1=true

[Order]
stop_loss_ratio_day_high=0.990
stop_loss_mode_day_high=vwap
hold_overnight_on_limit_up=true
exit_time_limit=132000000000
```

---

## 10. 待研究

- [ ] 拉更長回測（6 個月以上）驗證穩定性
- [ ] 部位管理（同天多筆交易的風險集中度）
- [ ] 與 VWAP 反彈策略的互補性
- [ ] 用 D-drive parquet 做更長期回測（需解決 ETF 缺失問題）
- [ ] 超額漲幅因子在更長數據下的穩定性
