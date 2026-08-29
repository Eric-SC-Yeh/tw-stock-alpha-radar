# Data Schema｜資料欄位

## 原始行情
- date
- ticker
- name
- market: TWSE / TPEx
- open
- high
- low
- close
- volume_shares
- turnover_twd

## 法人
- foreign_net_shares
- foreign_net_twd
- trust_net_shares
- trust_net_twd
- dealer_net_shares
- dealer_net_twd

## 技術衍生欄位
- ma5
- ma20
- ma60
- ma120
- bias_ma20_pct
- return_5d_pct
- return_20d_pct
- rsi14
- macd
- macd_signal
- macd_hist
- atr14
- volume_ratio_20d
- avg_turnover_20d
- relative_strength_20d
- high_20d
- high_60d

## 評分欄位
- market_score
- trend_score
- momentum_score
- volume_price_score
- chip_score
- breakout_score_component
- risk_adjustment
- total_score
- breakout_score
- grade
- stock_type: A / B
- exclusion_reason

## Dashboard CSV 最低欄位
可直接匯入 `dashboard.html`：
`ticker,name,market,close,turnover_billion,bias20,rsi14,trend,momentum,volume_price,chip,breakout,risk,total_score,breakout_score,signal`
