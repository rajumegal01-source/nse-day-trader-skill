# Trading Lab: સરળ ગુજરાતી માર્ગદર્શિકા

> **શૈક્ષણિક હેતુ માટે, રોકાણ સલાહ નથી.** (Educational only, not investment advice.)
> આ lab કોઈ broker સાથે વાત કરતું નથી અને કોઈ order મૂકતું નથી. તે ફક્ત મફત market data
> (Yahoo Finance) વાંચે છે અને પરિણામ છાપે છે.

## સૌથી પહેલાં સાચી વાત (honest note)

- Lab એ હજારો settings test કર્યા. જે આંકડા `memory.json` માં સારા દેખાય છે, તે મોટા ભાગે
  "પસંદગીનું નસીબ" છે, કારણ કે test ના દિવસો પણ પસંદગીમાં વપરાયા હતા.
- સૌથી પ્રામાણિક test એ **walk-forward** છે: જૂના દિવસો પરથી setting પસંદ કરો, પછી
  એ setting ને નવા, ન જોયેલા દિવસો પર ચલાવો.
- Intraday walk-forward (Nifty 100, 35 નવા દિવસો, 20,879 trades): સરેરાશ **-0.009% પ્રતિ trade**
  (cost પછી). એટલે કે **કોઈ સાબિત edge નથી**.
- Swing walk-forward (લગભગ 5 વર્ષ, 2,590 trades): pooled સરેરાશ +0.75% દેખાય છે, પણ 5 માંથી
  ફક્ત 2 test windows માં જ નફો હતો; એક મજબૂત bull window આખો આંકડો ઉપર ખેંચે છે. Default
  settings સાથે છેલ્લા 33% દિવસોમાં ત્રણેય setups ખોટમાં હતા. **સાબિત edge નથી.**
- Regime selector (કયા પ્રકારના દિવસે કયું setup): intraday અને swing બંનેમાં થોડો સુધારો દેખાયો,
  પણ સતત નહીં. એટલે તે **બંધ (off)** રાખ્યો છે.
- Real money પહેલાં ઓછામાં ઓછા 20-30 paper trades કરો. SEBI નો અભ્યાસ કહે છે કે F&O માં
  10 માંથી 9 જેટલા વ્યક્તિગત traders ખોટ કરે છે.

## શરૂઆત કેવી રીતે કરવી

**Android ફોન (Termux):**

```bash
pkg install -y python git
git clone https://github.com/rajumegal01-source/nse-day-trader-skill.git
bash nse-day-trader-skill/termux/run.sh
```

મેનુ ખુલશે: નંબર લખો અને Enter દબાવો. `q` થી બહાર.

**Google Colab (browser માં):** `notebooks/trading_lab_colab.ipynb` ખોલો અને ઉપરથી નીચે
દરેક cell ચલાવો.

**Computer:** repo clone કરો અને `python3 lab/terminal.py` ચલાવો.

## દરેક tool, એક લીટીમાં

| કામ | command | શું મળે |
|---|---|---|
| આજનું intraday scan | `python3 lab/lab.py scan` | આજે કયા નિયમ trigger થયા, તેમનું status |
| આજના picks (ફક્ત છાપો) | `python3 lab/alert.py --dry-run` | દિવસના શ્રેષ્ઠ picks (MAX_PER_DAY, default 2) |
| Walk-forward test | `python3 lab/walkforward.py --cache /tmp/y` | સૌથી પ્રામાણિક આંકડો |
| Report | `python3 lab/report.py wf` | નવા દિવસો vs જૂના આંકડા |
| F&O: option ની કિંમત | `python3 lab/fno.py price --spot 24000 --strike 24100 --days 6 --iv 13` | Black-Scholes કિંમત, delta, gamma, theta, vega |
| F&O: implied volatility | `python3 lab/fno.py iv --spot 24000 --strike 24100 --days 6 --premium 95` | IV % |
| F&O: payoff | `python3 lab/fno.py payoff iron_condor --strikes 23600,23800,24200,24400 --premiums 20,45,50,22 --symbol NIFTY` | expiry પર નફો/નુકસાન, breakeven, max profit/loss |
| F&O: size check | `python3 lab/fno.py size --symbol NIFTY --premium 120 --lots 2 --capital 100000` | premium મૂડીના કેટલા % છે |
| Swing scan | `python3 lab/swing.py scan` | daily chart પર breakout / pullback / 52-week high setups |
| Swing walk-forward | `python3 lab/swing.py wf --cache /tmp/yd` | 5 વર્ષનું out-of-sample પરિણામ |
| Pine scripts | `python3 lab/pine.py` | `pine/*.pine`: TradingView માટે ORB, FVG, BOS/CHoCH, PDH/PDL, CPR, swing breakout |
| Sector strength | `python3 lab/sector.py --stocks 10` | કયો sector NIFTY કરતાં મજબૂત, breadth |
| Journal stats | `python3 lab/journal_stats.py` | win %, expectancy (R), profit factor, setup / દિવસ પ્રમાણે |
| Market regime | `python3 lab/regime.py today` | આજનો દિવસ: trend-up / trend-down / range / high-vol |
| NSE calendar | `python3 lab/calendar_nse.py` | આજે market ચાલુ? આગામી NIFTY / BANKNIFTY expiry, બાકી રજાઓ |
| Facebook post | `python3 lab/content.py` | ગુજરાતી + English post અને SVG chart (`content_out/`) |

## થોડું સમજીએ

- **Lot size:** `lab/lot_sizes.csv` માં છે (NIFTY 65, BANKNIFTY 30, Nov 2026). NSE લોટ સાઇઝ
  બદલે છે, એટલે હંમેશા NSE પર ચકાસો.
- **Option વેચવું (selling):** તેમાં exchange margin જોઈએ (ઘણી વાર એક લોટ માટે ₹1-2 લાખ).
  આ tool margin ગણતું નથી. Straddle / strangle વેચવામાં નુકસાન અમર્યાદિત હોઈ શકે છે.
- **Expiry:** Sep 2025 થી NIFTY weekly મંગળવારે, NIFTY અને BANKNIFTY monthly મહિનાના છેલ્લા
  મંગળવારે. મંગળવારે રજા હોય તો આગલા trading દિવસે (દા.ત. 10 Nov 2026 ની રજા એટલે 9 Nov).
- **R-multiple:** 1R = entry થી stop સુધીનું જોખમ. +2R એટલે જોખમ કરતાં બમણો નફો, -1R એટલે stop.
- **Relative strength (RS):** stock નું વળતર ઓછા NIFTY નું વળતર. RS +3 એટલે NIFTY કરતાં 3% વધુ.
- **Regime:** ADX (trend ની તાકાત), ATR (રોજની હલચલ) અને EMA20 ની દિશા પરથી NIFTY નો દિવસ.
- **Facebook post:** tool "buy" / "sell" શબ્દો લખતું નથી; ફક્ત "setup example" અને "rule output".
  Post મૂકતાં પહેલાં જાતે વાંચો. Tool જાતે કંઈ post કરતું નથી.

## વૈકલ્પિક ફિલ્ટર (બંધ છે, off by default)

- `SECTOR_STRONG=1 python3 lab/alert.py`: ફક્ત top 3 sectors ના picks. Out-of-sample test નથી થયો.
- `REGIME_SELECT=1 python3 lab/alert.py`: ફક્ત આજના regime માં સારું ચાલેલું setup. Test માં સ્પષ્ટ ફાયદો ન દેખાયો.
- `MAX_PER_DAY=5`: દિવસના picks ની મર્યાદા (default 2).

---

**યાદ રાખો:** backtest નો સારો આંકડો વચન નથી. પહેલાં paper trade કરો, નાની રકમથી શીખો,
અને નુકસાન સહન કરી શકો એટલું જ જોખમ લો. **શૈક્ષણિક હેતુ માટે, રોકાણ સલાહ નથી.**
