# Алгоритмический трейдинг на Polymarket и Kalshi после CTF Exchange v2: отчёт для $200-бюджета

## TL;DR

- **Главный вывод: с $200 и Hetzner-VPS за €5-10/мес ты не построишь прибыльный latency-arb бот** — этот класс стратегий убили динамические taker-комиссии Polymarket (пик 1.80% на crypto при цене 0.50). История «бот превратил $313 в $437,600 за месяц» (wallet 0x8dxd, Dexter's Lab @DextersSolab, 5 января 2026) реальна, но это была декабрь 2025 — стратегия мертва как раз потому, что её и заметили. Сейчас твой реалистичный edge — **maker-only стратегии на geopolitics-маркетах (0% taker fees) и редистрибуция таких fees** в виде maker rebate (25% от taker pool, 20% на crypto, выплаты ежедневно в pUSD).
- **CTF Exchange V2 запустился 28 апреля 2026** (не 22-го, как в твоей формулировке), и реально изменил архитектуру: новый коллатерал pUSD (ERC-20, 1:1 USDC), новая структура ордеров без `nonce`/`feeRateBps`/`taker` и с добавленным `timestamp`/`metadata`/`builder`, EIP-712 domain version `"2"`. Из-за миграции все открытые ордера были сброшены — у тебя свежий 6-недельный период данных для бэктестов через Polygon RPC + Gamma API. Старый `py-clob-client` больше не работает на production; нужен **`py-clob-client-v2`** (v1.0.1+) или новый унифицированный `py-sdk`.
- **Казахстан НЕ в стоп-листе ни Polymarket, ни Kalshi** (Polymarket блокирует 33 страны на 23 апреля 2026 — KZ среди них нет; Kalshi доступен в 143 странах, KZ не в списке из ~52 restricted). Polymarket пушит KYC только для high-volume (7-figure positions) — мелкому трейдеру через MetaMask и Polygon pUSD KYC не требуется. Kalshi с не-US — debit card / crypto / wire only, без ACH; и юридической защиты CFTC у тебя нет. **Honest take: строй на Polymarket, Kalshi оставь как источник цен для cross-market мониторинга.**

---

## Key Findings (что важно понять до старта)

1. **CTF Exchange V2 — это не «новый CLOB», это полная пересборка контрактного слоя.** Solidity апгрейднут с 0.8.15 до 0.8.30 (Solady вместо OpenZeppelin для gas-savings), структура ордеров упрощена, fees теперь собираются on-chain в момент match (не зашиты в ордер), а батч-операции mint/merge экономят до 51% газа на multi-maker matches. Контракты прошли аудиты Cantina и Quantstamp, bug bounty активный.

2. **Гонка вооружений уже закончилась — ты в неё опоздал.** 14 из 20 самых прибыльных кошельков на Polymarket — боты (Stacy Muur @stacy_muur, 16 марта 2026). Согласно on-chain анализу IMDEA Networks (Q3 2025 — Q1 2026, опубликовано через Medium/ILLUMINATION «Beyond Simple Arbitrage»): «Average arbitrage opportunity duration: 2.7 seconds (down from 12.3 seconds in 2024). 73% of arbitrage profits captured by sub-100ms execution bots.» Bid-ask spreads сжались с **4.5% в 2023 до ~1.2% к концу 2025** (TradeTheOutcome.com / Prediction Hunt Blog). Маркеты с обычным YES + NO < 1.00 — мёртвая стратегия для retail.

3. **Динамические taker fees убили latency-arb на 15-минутных crypto-маркетах.** Polymarket ввёл их в начале 2026 именно как ответ на бот 0x8dxd. Формула: `fee = C × 0.07 × p × (1-p)` на crypto, пик ~1.56-1.80% при цене $0.50. Чтобы latency-arb работал, нужен edge > 1.80% — раньше edge был 1-2%, сейчас он съедается комиссией.

4. **Polygon-газ микроскопический — не bottleneck.** Базовая base fee 25 gwei minimum, типичная транзакция стоит долю цента. Реальная проблема не газ, а сборы Polymarket (1.56% peak на crypto) и комиссии on/off-ramp (MoonPay debit card 2-3%).

5. **Maker rebates + geopolitics — единственные ниши с положительным EV на маленьком капитале.** Geopolitics-маркеты на Polymarket — fee-free permanently. Maker rebates на остальных категориях платят 25% (20% на crypto) от taker fee pool, ежедневно в pUSD, минимум $1 для выплаты.

6. **Бот-фольклор и реальность.** История «бот с $1-2» — это **миф**, искажение истории 0x8dxd (стартовый bankroll был **$313**, не $1; источник — Dexter's Lab @DextersSolab, X-пост 5 января 2026). При этом этот же кошелёк позже работал с позициями $500-50,000 на маркет. Стратегия — latency arbitrage между Binance/Coinbase спот и Polymarket 15-min markets; **она больше не работает после введения dynamic fees.** Согласно IMDEA Networks (86M транзакций, апрель 2024 – декабрь 2025, опубликовано через ChainCatcher/MEXC News): **«Only 0.51% of Polymarket wallets have achieved profits exceeding $1,000.»**

---

## Details

### 1. Polymarket CTF Exchange V2 (post-28 апреля 2026)

**Что изменилось на уровне контракта:**
- Новый exchange address: `0xE111180000d2663C0091e4f400237545B87B996B` (старый `0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E` отключён)
- Neg-Risk exchange: `0xe2222d279d744050d28e00520010520000310F59`
- EIP-712 Exchange domain version: `"2"` (ClobAuth остался `"1"`)
- Order struct: убраны `nonce`, `feeRateBps`, `taker`; добавлены `timestamp` (миллисекунды), `metadata`, `builder`
- Коллатерал: `pUSD` (Polymarket USD, 1:1 USDC, ERC-20 на Polygon)
- Onchain fee collection: fees теперь не embedded в ордер — динамически рассчитываются operator-ом в момент match через `getClobMarketInfo()`
- `pauseUser` / `unpauseUser` заменили on-chain cancel; nonce-system удалена

**CLOB endpoints:**
- Production: `https://clob.polymarket.com`
- WebSocket market data: `wss://ws-subscriptions-clob.polymarket.com/ws/market`
- Real-Time Data Socket (RTDS, для Chainlink price feeds и комментариев): `wss://ws-live-data.polymarket.com`
- Gamma API (market discovery, без аутентификации): `https://gamma-api.polymarket.com`

**Rate limits (после rollout V2):**
- `POST /order`: 120,000 / 10 минут (~200/s sustained)
- `DELETE /order`: 120,000 / 10 минут
- `POST /orders` (batch): 2000 / 10s burst
- L1/L2 auth не поменялся — старые API-ключи работают

**Документированные edges/issues после миграции:**
- На rollout 28 апреля Polymarket выкатил `$1M liquidity rewards` ($500K за первые 2 часа, $500K на остаток дня) — это был легитимный maker-only edge на сутки, сейчас уже отыгран
- Известный пост-мигра quirk (TradoxVPS, 4 мая): новые account flows используют **deterministic deposit wallets** и **ERC-1271 signatures** (signature type 3). Если ставишь signature_type неправильно — orders отклоняются по "insufficient balance" даже при наличии денег. Это самая частая ошибка в issues `py-clob-client-v2` (см. issues #70-#88, май-июнь 2026)
- Maker Rebates Program теперь имеет дополнительный **30% taker rebate бонус** для участников с объёмом >$250,000 в период 15 мая — 30 июня 2026 (т.е. для тебя нерелевантно при $200)

### 2. Kalshi (май-июнь 2026)

**Структура и комиссии:**
- Структура: классический CLOB, цены $0.01–$0.99, бинарные YES/NO
- Taker fee: `fee = round(multiplier × price × (1−price), 2)` per contract, multiplier 0.07 на большинстве категорий → **пик ~1.75% эффективной комиссии при $0.50**
- Maker fee: на большинстве маркетов **$0.00** благодаря rounding ($0.005 округляется в ноль)
- Settlement fee: $0
- ACH депозит/вывод бесплатные (но **только для US users**)
- Для не-US: debit card (2% fee, мин $2 вывод), wire, crypto

**Доступ из Казахстана:** Kazakhstan **не** в стоп-листе из ~52 restricted jurisdictions. Регистрация возможна — через crypto-депозит или debit card. **Но**: ты не получишь юридической защиты CFTC; в случае спора Kalshi твою претензию по non-US-протоколу обрабатывать не будет, и нет ACH для cheap fiat in/out.

**Свежие изменения мая-июня 2026:**
- 3 июня: запуск **BTCPERP** (Bitcoin perpetual futures, CFTC-cleared, 24/7, cash-settled USD, 8-hour funding) — **только для US users** в первой фазе
- 4 июня: запуск ETH perpetual futures по той же модели
- Filed certifications для XRP/SOL/DOGE/SHIB/HBAR/XLM perps (CFTC review pending, 1 июня)
- API изменения: deprecation `/portfolio/orders*` в пользу `/portfolio/events/orders` — миграция к **14 мая 2026** (повышение rate-limit cost для старых endpoints)
- Token-cost rate-limit система с raw read/write budgets — новый Paragon tier для high-volume

**Демо-окружение:** `demo-api.kalshi.com` — **полный sandbox** с фейковыми деньгами. Это огромный плюс над Polymarket, где testnet практически нет.

**Polymarket vs Kalshi для тебя:**
| Параметр | Polymarket | Kalshi |
|---|---|---|
| Доступ из KZ | Да, без KYC до 7-figure | Да, но без US-attached защиты |
| Funding | Crypto (Polygon USDC) — околонулевые fees | Debit card 2% / wire / crypto |
| Demo | Нет (Amoy testnet не для CLOB) | Да, `demo-api.kalshi.com` |
| Geopolitics fee | 0% | Стандарт ~7% multiplier |
| Crypto micro-markets | 15-мин BTC/ETH/SOL | Hourly BTC/ETH/SOL/XRP |
| Liquidity для $50-200 | Высокая на топ-маркетах | Высокая, но более fragmented |
| Регулятивный риск для KZ | Низкий | Низкий (off-shore для тебя) |

**Рекомендация**: основная платформа — Polymarket; Kalshi — источник цен для cross-market мониторинга (но платформа Hyperliquid HIP-4 outcome markets — на конкретного игрока агрессивнее).

### 3. Документированные неэффективности (после апреля 2026)

**Что мертво или умирает:**
- **YES + NO < 1.00 простой arb** — Trade The Outcome подтверждает (со ссылками на IMDEA-исследование): эта простая стратегия принесла $40M между апрелем 2024 и апрелем 2025 — past tense. Spreads сжались с 4.5% до 1.2%, окно 2.7 сек, нужна sub-100ms execution
- **Latency arb Binance→Polymarket на 15-min crypto** — убит динамическими fees. На 50¢ контракте пик fee ~1.56-1.80%; типичный edge раньше был 1-2%
- **Sniping last-second resolution** — Chainlink Data Streams теперь auto-settle 15-минутные крипто-маркеты практически мгновенно после expiry; нет «человеческой задержки»

**Что ещё работает (но требует чёткого edge):**
- **Cross-market arbitrage Polymarket ↔ Kalshi на не-crypto событиях** — резолюционные правила различаются (классический пример: government shutdown маркет резолвился по-разному на двух платформах в 2024). Возможности есть, но **читай rulebook каждой стороны до открытия позиций** — иначе обе ноги могут проиграть
- **Combinatorial arbitrage** — Trump won ≤ Republican won; если связанные маркеты расходятся по логике (e.g., Trump @ 55%, Republican @ 50%), это математически невозможная цена. IMDEA нашли 7,000+ маркетов с измеримыми combinatorial mispricings — но это требует капитала на multi-leg позиции
- **Maker provision** в нишевых маркетах (long-tail politics, weather, niche sports) — где HFT не охватывает, spreads 2-5%, и ты собираешь rebate 25%
- **Resolution disputes** — UMA disputes (1,150+ в 2026 vs весь 2025 total) создают волатильность в последние часы. Можно играть на возврат к фундаментальной вероятности после dispute — но это **высокий риск**: смотри $60M MicroStrategy кейс (1-2 июня 2026), где маркет с очевидным «YES» резолвится в «NO» через token-weighted vote

**Discord/X-каналы для мониторинга edge-discussion:**
- Official Polymarket Discord (developer support в #devs)
- BetMoar (`betmoar.fun`) — крупнейший third-party терминал с whale tracking
- PolyTraderBot Discord — обмен setups
- @DextersSolab, @stacy_muur, @lookonchain, @igor_mikerin — X-аккаунты с глубоким Polymarket-анализом
- Subgraph Analytics (`github.com/PaulieB14/polymarket-subgraph-analytics`) — query examples для The Graph

### 4. Crypto-specific prediction markets

**Polymarket crypto category (на 6 июня 2026):**
- 313 маркетов в категории Crypto, 9 в 1-Hour подкатегории, 35 в Bitcoin
- Резолюция 15-мин и 1-час BTC/ETH/SOL — через **Chainlink Data Streams + Chainlink Automation** (low-latency, on-chain auto-settle), не через UMA
- Спот-источник для резолюции — Chainlink aggregated price feed, **не** один единственный exchange
- Order book depth на 5-минутных контрактах: $5,000-$15,000 на сторону (CoinDesk Feb 2026) — для тебя ($50-200 позиции) ликвидности более чем достаточно
- Спреды: 0.5-2¢ на ликвидных крипто-маркетах в середине цены; 5-15¢ на extremes

**Kalshi crypto:**
- Hourly BTC/ETH/SOL/XRP markets с volume $2K-75K на маркет
- Резолюция по CF Benchmarks reference rate (тот же провайдер, что для CME XRP futures)
- 5pm EST-snapshot за день — не настолько high-frequency как Polymarket 15-мин
- Доступ к BTCPERP / ETHPERP только для US users (на 6 июня 2026)

**Binance↔Polymarket арбитраж: реалистичная оценка**
- На Polymarket 5-min BTC контракт спот-движение Binance отражается через **30-90 секунд**, не мгновенно (TradoxVPS measurements)
- При европейском VPS (Dublin/Amsterdam): roundtrip к Polymarket CLOB **5-10 ms**; из US East — 130 ms
- Чтобы получить edge: нужно реагировать на спот-move >0.3% за 60 сек **раньше**, чем market makers Polymarket переоценят
- **Проблема для $200**: пиковая taker fee 1.56% (на 50¢) делает entry > 1.6% невыгодным; entry около extremes (>$0.85) — там fee почти 0%, но и edge маленький

**Конкретный пример сценария:**
- BTC падает с $77K до $75,500 на Binance за 60 секунд (-1.94%)
- Polymarket «BTC > $76K в следующие 15 мин» был на 50¢, после первой реакции (15-30 сек) уходит к 35¢
- Купить NO @ $0.65 в первые 10-15 сек: при confirm падения NO растёт к $0.85-0.95
- Edge ~20¢ на $1 = 20%, но taker fee на $0.65 = `1 × 0.07 × 0.65 × 0.35 × 100 = 1.59¢` per share = ~2.5% от entry. После fee net ~17-18%
- **Реалистично для $50 позиции — выигрыш $8-9 в идеальном случае. Это ~6-12 таких setups в день при удаче.**

### 5. AI-news prediction bot — реалистично ли?

**Что монетизирует news bot:**
- Не предсказание будущего, а **скорость классификации** новости и **скорость reroute** ордера до того, как маркет переоценит
- Latency-требование: десятки секунд для long-tail событий (politics, geopolitics, court rulings), single seconds для high-frequency (Federal Reserve announcements)

**Стек, который реально работает (по описанию QuantVPS и других):**
- Источники: Twitter/X API ($100/мес basic tier) — основной источник, RSS news feeds (бесплатно), Polymarket RTDS WebSocket (бесплатно, через `wss://ws-live-data.polymarket.com`)
- Trigger: keyword/regex match на topic-specific feed → LLM-классификатор (Claude Haiku / GPT-4o-mini для cost-efficiency, ~$0.0005 за запрос) → propensity score
- Если score > threshold → запрос orderbook через Gamma API → отправка лимит-ордера через `py-clob-client-v2`

**Бутылочные горлышки на $10-20/мес VPS:**
- Twitter API basic tier — 100 reads/15 мин — **недостаточно** для serious news monitoring
- Бесплатные scrapers новостных сайтов — лимиты, антибот защита
- LLM call latency: 200-500 мс на Claude Haiku — нормально для slow news, **смертельно** для Federal-Reserve-style события

**Документированные случаи (с осторожностью — все цифры со слов):**
- «ilovecircle» бот: $2.2M за 2 месяца, 74% win rate, AI-based probability модели (igor_mikerin, 23 декабря 2025)
- Weather bot: $1,800 net profit на температурных маркетах (TradoxVPS)
- News-based bot Jan 14 2026 (witness recants testimony): пример из медиум-статьи — захватил 13¢ spread на $2,000 позиции (~$896 за 10 минут)
- **Caveat**: эти цифры из медиум-статей и Twitter-постов; невозможно независимо проверить

**Реалистичный ответ для тебя:** AI-news bot на $200 с европейским VPS — **возможен, но не как первый проект**. Сначала нужно построить baseline (стабильный market-making бот), потом наслаивать news-фильтр.

### 6. VPS-архитектура

**Latency-таблица (TradoxVPS measurements, май 2026 — single-source, см. caveats):**
| Локация VPS | RTT до Polymarket CLOB (AWS eu-west-2) |
|---|---|
| Dublin (Ireland) | < 5 мс |
| Amsterdam | ~10 мс |
| Frankfurt | ~15 мс |
| Helsinki (Hetzner) | ~25-30 мс |
| US East | ~130 мс |

**Recommended providers для $10-20/мес:**
- **Hetzner Cloud CX22** (Helsinki/Falkenstein/Nuremberg): €5-6/мес, 2 vCPU, 4GB RAM, 40GB NVMe — самый дешёвый workable
- **Contabo VPS S** (Düsseldorf): $6-7/мес, 4 vCPU, 8GB RAM — мощнее, но сетевой jitter под нагрузкой (упомянуто в Polymarkets.co.il тестах)
- **Vultr High Frequency** (Amsterdam/Frankfurt): $12/мес, 1 vCPU, 1GB RAM, NVMe
- **DigitalOcean** (AMS3): $12/мес, 2GB RAM
- **TradingVPS/TradoxVPS Dublin**: $30-60+/мес — overkill для твоего бюджета и стратегии

**Honest take:** для maker-only и copy-trading стратегий **Hetzner Helsinki за €5 хватит за глаза**. Ты в любом случае не конкуришь с co-located HFT (NY4/LD4 sub-1ms); твоя цель — стабильный 24/7 uptime, не sub-100ms execution.

**Стек:**
- **Python** — основной язык сообщества (`py-clob-client-v2` v1.0.1, активно поддерживается, 139 stars, открытые issues в мае-июне 2026 показывают живое developer-сообщество)
- **TypeScript** — для тех, кто хочет официальный hot-swap SDK
- **Rust** — официальный `rs-clob-client` существует, но V2-only Rust SDK ещё не выпущен (на 6 июня 2026)
- **WebSocket-only архитектура** — не polling. Подписаться на `wss://ws-subscriptions-clob.polymarket.com/ws/market` для orderbook updates, не REST `/book` polling

Минимальный Python-скелет под V2:

```python
# pip install py_clob_client_v2 viem-py  # см. requirements.txt репозитория
import os
from py_clob_client_v2 import ClobClient, OrderArgs, OrderType, Side, PartialCreateOrderOptions

host = "https://clob.polymarket.com"
chain_id = 137  # Polygon mainnet; 80002 для Amoy (но там нет ликвидности)

# Шаг 1: получить API-кредентиалы из приватника (L1 auth)
client = ClobClient(host=host, chain_id=chain_id, key=os.environ["PK"])
creds = client.create_or_derive_api_key()

# Шаг 2: инициализировать клиент с полной аутентификацией (L1 + L2)
client = ClobClient(host=host, chain_id=chain_id, key=os.environ["PK"], creds=creds)

resp = client.create_and_post_order(
    order_args=OrderArgs(
        token_id="<TOKEN_ID>",  # из gamma-api.polymarket.com/markets
        price=0.40,
        side=Side.BUY,
        size=10,  # 10 shares = $4 risk при цене 0.40
    ),
    options=PartialCreateOrderOptions(tick_size="0.01"),
    order_type=OrderType.GTC,  # good-till-cancelled, делает тебя maker-ом
)
print(resp)
```

### 7. Историческая data для бэктеста

**Источники с пост-V2 данными:**
- **`github.com/warproxxx/poly_data`** — Python-пайплайн, читает `OrderFilled` events напрямую с CTF Exchange V2 contract (`0xE111180000d2663C0091e4f400237545B87B996B`) через Polygon JSON-RPC, мерджит с Gamma API. **Это то, что тебе нужно** — резумабельный fetch, экспорт в `data/orderFilled.csv` и `processed/trades.csv`. С момента 28 апреля можешь подтянуть ~6 недель пост-V2 данных бесплатно
- **Polymarket CLOB Historical Timeseries API** — `GET /prices-history`, цены по token_id; рабочая Jupyter Notebook есть в docs
- **The Graph subgraphs** — `QmdyCguLEisTtQFveEkvMhTH7UzjyhnrF9kpvhYeG4QX8a` для основных market/positions/trade данных, плюс отдельные subgraphs для orderbook depth и market names (см. `github.com/PaulieB14/polymarket-subgraph-analytics`)
- **Kaggle dataset** — Polymarket Historical Prices ~8.9M data points, 11 файлов / 1GB (актуальность ограниченная — гл. образом 2024-2025)

**Для свежего back-test (3-6 недель пост-V2):**
```bash
git clone https://github.com/warproxxx/poly_data
export POLYGON_RPC_URL="https://polygon-rpc.com"  # или платный Alchemy/QuickNode
export POLYGON_MAX_BLOCK_RANGE=1000
python -m poly_data.update
```
Ожидай ~5-10 GB сырого CSV для 6 недель top-маркетов. Бесплатные публичные RPC (`polygon-rpc.com`) дадут rate-limit при сканировании; за $20-30/мес Alchemy/QuickNode сэкономят дни вместо часов.

**Sandboxing / testnet:**
- **Polymarket: НЕТ полноценного testnet.** Amoy chain_id `80002` поддерживается в `py-clob-client-v2`, но нет real liquidity / market-making. Полу-официальная рекомендация (Chainstack docs) — тестировать **с мизерными ордерами (≤ $1) и FOK/FAK типами** на mainnet
- **Kalshi: ДА**, `demo-api.kalshi.com` — полный sandbox с fake-money, идеально для unit-tests твоей логики

### 8. Реалистичный edge на $100-500 капитала

**Жёсткая правда:**
- Polymarket на 80% — net-loser среда. По on-chain анализу IMDEA Networks 86M транзакций (апрель 2024 – декабрь 2025, опубликовано через ChainCatcher/MEXC News): **только 0.51% всех кошельков когда-либо профитили >$1,000**
- 14 из 20 топ-прибыльных кошельков — боты (Stacy Muur, март 2026)
- Без edge > 1.8% после fees — статистически отрицательный EV

**Mat по комиссиям для $200 bankroll:**
- Один типичный $50 trade на crypto 50¢: fee = $50 × 0.07 × 0.5 × 0.5 = $0.875 (1.75% от $50)
- Polygon-газ на это: $0.0003-0.001
- **Net breakeven при ROI на trade ~1.76%** — для бота с 60% win rate это значит средний выигрыш должен быть ≥ 3% после losses

**Sizing для $200:**
- Max 3-5 одновременных позиций × $40-50 каждая
- Никогда > 25% bankroll в одной позиции
- При drawdown 30% — стоп и пересмотр стратегии

**$1-2 капитал — это миф.** История 0x8dxd ($313→$437K за месяц, декабрь 2025 → 6 января 2026) реальна, но это были **стартовые $313** (не $1), и стратегия (latency arb на 15-мин crypto) **умерла** после введения dynamic fees. На январский 2026 момент 0x8dxd уже работал с per-trade sizes $500-50,000 (после compounding). Первоисточник — твит @DextersSolab от 5 января 2026; корроборация Finbold, BingX, KuCoin, Finance Magnates.

**Honest verdict для тебя:**
> С $200 запускать первый бот в продакшне для дохода — **финансово невыгодно** в большинстве сценариев. Цена обучения (failed trades, API quirks, неправильно расчитанные comission) превысит сам капитал. **Build the code now, deploy when capital scales к $2-5K минимум.** $200 имеет смысл потратить только на (а) Hetzner за €60/год + (б) маленькие живые тесты для валидации логики, а **не как trading capital**.

### 9. Risk и reality check

**Конкуренция:**
- 14/20 top wallets = боты. Большинство — institutional setups с co-location и dedicated RPC nodes
- **Wintermute** (top market maker в крипте, $3.5 trillion annual trading volume across 70+ exchanges) официально подтвердил двусторонюю ликвидность на Polymarket и Kalshi **29 мая 2026** (твит @wintermute_t, цитировано Decrypt: «Wintermute confirmed it's providing two-sided liquidity to major prediction platforms… The venues include Polymarket and Kalshi.»). Spreads будут ещё больше сжиматься
- **Galaxy Digital** открыл institutional OTC prediction markets desk; первый сделка — **event swap с Arca 2 июня 2026 под ISDA-агременты** на принятие CLARITY Act (Digital Asset Market Clarity Act), номинал $10M: «Arca pays Galaxy if the bill passes before 2027; Galaxy pays Arca if it does not» (PRNewswire, CoinDesk). Это не просто «trade на Kalshi», а bilateral OTC swap — но показывает, куда движется институциональная глубина

**Common ways to lose money:**
1. **Resolution divergence cross-platform**: купил YES Polymarket + NO Kalshi на «one event» — разные resolution criteria, обе ноги проиграли (классический gov-shutdown 2024 case)
2. **UMA dispute risk на politics/geopolitics**: MicroStrategy 1-2 июня 2026 кейс — маркет «MSTR sells any Bitcoin by May 31?» с очевидным YES (8-K filed) резолвится в NO через token-weighted vote whale-ов; $60M volume. **Защита: продавай winners на $0.95+ вместо holding до $1.00**
3. **Ghost fills (legacy V1)**: на V2 эту проблему **решили** через deterministic deposit wallets + ERC-1271, но новые users теряются на signature_type=3 setup
4. **Withdrawal path для KZ**: нет easy fiat off-ramp на Polygon → KZT. Самое реальное — USDC → Binance → P2P в KZT (с потерями ~1-2% на стоимости конверсии)

**Smart contract risk:**
- CTFv2 контракты прошли **Cantina + Quantstamp audits**; bug bounty активный на Cantina
- Реентрэнси-guard убран (operator-only access pattern); registry token-registration убрана (любой valid CTF token ID торгуется)
- Известных эксплойтов post-launch на 6 июня 2026 нет

**Газ-экономика:**
- Polygon базовая base fee 25 gwei minimum (с 2024), priority fee 25-280 gwei в активные часы
- Транзакция = 200K газа × 30 gwei × $0.40/POL = **$0.0024**. Бесплатно практически
- В отличие от Ethereum, газ на Polygon — **не bottleneck**. Если бот теряет деньги — не на газе

**KZ-specific regulatory:**
- Казахстан **не** под US/EU sanctions для crypto deals
- Декларация доходов: в Казахстане criptocurrency-доходы — **облагаемый налог** (10% IIT для резидентов с 2024); Polymarket transactions технически попадают под trading income
- Capital controls: КЗ не имеет hard capital controls для крипто; вывод через P2P на Binance KZ работает (но bank conversion ~1-2%)

### 10. Concrete actionable recommendations

**Месяц 1 — учёба без капитала:**
1. Подними Hetzner CX22 за €5/мес в Helsinki или Falkenstein. Ubuntu 22.04
2. Установи `py-clob-client-v2 >= 1.0.1`. Прочитай code в `Polymarket/clob-client-v2` (TypeScript reference) и `py-clob-client-v2/examples/`
3. Подключись к `demo-api.kalshi.com` — там твой основной sandbox. Все trading-logic unit-тесты прогоняй здесь
4. Параллельно — скачай Polymarket исторические данные через `warproxxx/poly_data` (28 апреля → сегодня). 6 недель — достаточно для baseline backtest
5. Подпишись на BetMoar Discord, Polymarket Devs Discord. **Молчи и читай** месяц

**Месяц 2 — paper trading:**
1. Реализуй простейший maker-bot на geopolitics-маркетах (0% fees). Quote both sides с фиксированным $0.02 spread, max position size = $5
2. Параллельно — copy-trading-tracker на 0x8dxd и top-10 wallets через `Xyryllium/polymarket-tracker-bot` или `warproxxx/poly_data`. **Только запись в БД, не реальные trades**
3. Сравни paper-pnl с реальной execution price на mainnet (через test orders $1)
4. Бэктест Binance↔Polymarket latency-arb на исторических данных. Посчитай fee-adjusted EV. **Я ставлю — отрицательный**

**Месяц 3 — мизерный реальный капитал ($50):**
1. Залей $50 в pUSD через Binance → MetaMask на Polygon (НЕ через MoonPay — там 2-3% fee)
2. Запусти ровно одну стратегию: **maker-only на geopolitics**, max $5 per position, 3-5 positions parallel
3. Цель — не доход, а validation full execution flow и log analysis 24/7
4. Если paper p&l ≈ live p&l (отклонение < 10%), и нет повторяющихся технических ошибок — переходи к шагу 4

**Месяц 4+ — масштабирование (если есть результат):**
1. Долей до $200 bankroll. Расширь: maker provision на long-tail politics, sports на низко-ликвидных рынках
2. **НЕ** запускай latency-arb на crypto без минимум $2K bankroll. Cost структура не позволяет
3. Если бот стабильно положительный 3 месяца подряд при $200 — **тогда** можно думать о scale до $1-2K

**Стратегия с лучшим edge/complexity ratio для тебя:**
- **Maker provision на низко-ликвидных politics/geopolitics-маркетах** с долгим time-to-resolution. Spreads 3-8¢, 0% taker fees (geopolitics) или 25% maker rebate (politics). Низкая HFT-конкуренция, low latency requirements, robust к network jitter

**GitHub-репы для изучения:**
- `Polymarket/py-clob-client-v2` — официальный Python SDK V2
- `Polymarket/clob-client-v2` — TypeScript reference (читать обязательно)
- `Polymarket/ctf-exchange-v2` — Solidity-контракты с подробным README
- `nautechsystems/nautilus_trader` (issue #3844) — pro-grade trading framework, есть V2 миграция
- `CarlosIbCu/polymarket-kalshi-btc-arbitrage-bot` — рабочий пример cross-platform монитора
- `warproxxx/poly_data` — пайплайн исторических данных
- `txbabaxyz/polyrec` — real-time дашборд для BTC 15-мин с Chainlink + Binance feeds (отличный референс архитектуры)
- `Xyryllium/polymarket-tracker-bot` — copy-trading tracker через Discord
- `Schubert-Tom/polymarket-binance-arbitrage` — академический proof-of-concept Polymarket↔Binance options-arb
- `harish-garg/Awesome-Polymarket-Tools` — мета-список 170+ инструментов

**X-аккаунты для мониторинга:**
- @Polymarket / @PolymarketDevs — official
- @DextersSolab — глубокий on-chain анализ
- @stacy_muur — bot/HFT analysis
- @lookonchain — whale tracking
- @igor_mikerin — AI-trading кейсы
- @wintermute_t — institutional liquidity insights

---

## Recommendations (по приоритету)

1. **Не запускай trading-бот с $200 на доход. Запускай его на обучение и инфраструктуру.** Брейкивен mat говорит, что при типичных fees 1.5-1.8% и win rate 55-60% твой ожидаемый месячный return -10 до +5%. Это в лучшем случае wash, в худшем — slow bleed.

2. **Дешёвый VPS € 5/мес у Hetzner в Helsinki — достаточно** для всех твоих стратегий (maker provision, copy trading, news monitoring). Не плати $30+ за «trading-tuned VPS», пока bankroll < $5K.

3. **Главная развилка stack:** Python + `py-clob-client-v2` + `httpx[http2]` для async, asyncio loop, не threading. Логи — structlog с JSON-output на stdout, потом в `journalctl` через systemd unit.

4. **Бэктестинг до live trading.** Скачай 6 недель пост-V2 данных через `warproxxx/poly_data`, прогоняй любую стратегию **минимум 1000 simulated trades** до live. Если backtest показывает Sharpe < 1.0 — стратегия идёт в мусор, не в продакшн.

5. **Никогда не торгуй latency-arb crypto 15-min с < $2K bankroll.** Динамические fees на этих маркетах математически делают эту стратегию убыточной на твоём capital level.

6. **Цель за 6 месяцев — не deposit-to-trading-profit, а deposit-to-validated-codebase.** К декабрю 2026 у тебя должен быть production-ready бот с подтверждённым backtest-PnL > $0 на 90-дневном окне. **Только тогда** есть смысл искать $2-5K для real deployment.

**Trigger to change strategy:**
- Если за 60 дней paper-trading на geopolitics-maker не получается стабильно +1-3% месячного return — стратегия не для тебя; переходи на news-bot или копи top-wallets
- Если Polymarket добавит fee на geopolitics — твой главный edge исчезнет, перезапланируй на dispute-arbitrage или cross-market

---

## Caveats

1. **Эта область двигается недельно.** Между сбором данных (6 июня 2026) и моментом, когда ты построишь production-бота, многое поменяется. Дальнейшие Spain/India/Indonesia bans, fee changes, новые конкуренты вроде Hyperliquid HIP-4 — всё это влияет на структуру edge.

2. **Все цифры про прибыльных ботов — second-hand.** $313→$437K (0x8dxd), $2.2M за 2 месяца (ilovecircle), $116K в день (Bidou28old) — это цифры из Twitter/Medium-постов, которые невозможно полностью верифицировать. Они **похоже** правдивы (on-chain данные подтверждают для 0x8dxd через Finbold/KuCoin корроборацию), но selection bias огромный: мы видим выживших, а не тысячи разорившихся.

3. **Spain заблокировала Polymarket+Kalshi 26 мая 2026, India заблокировала 21 мая, Indonesia — 25 мая, Portugal — в январе.** Тренд — больше ограничений, не меньше. Казахстан **сегодня** не в списке, но я не могу гарантировать, что не появится в Q3-Q4 2026.

4. **UMA-disputes остаются структурным риском.** MicroStrategy case 1-2 июня 2026 показал, что даже на объективно резолвящемся событии ($60M volume) token-vote whales могут навязать неправильную резолюцию. Согласно Wall Street Journal investigation (май 2026, через The Defiant): «в большинстве disputed Polymarket markets более половины UMA votes пришли от десяти крупнейших wallets, как минимум 60% активных UMA voters могут быть связаны с живыми Polymarket-аккаунтами, и примерно один из пяти disputes имел минимум одного voter с финансовым stake в контракте, по которому он голосовал». **Это не bug, это feature** до тех пор, пока UMA-governance не реформируется. Не держи позиции до резолюции на disputed-prone маркетах.

5. **Налогообложение в Казахстане для crypto-trading доходов — налогооблагаемое.** 10% IIT с прибыли по новым правилам (2024). Если ведёшь Polymarket-trading серьёзно — веди учёт fills для декларации.

6. **Polymarket KYC сейчас опциональный для retail (≤7-figure), но это может измениться.** US House Oversight Committee deadline 5 июня 2026 — Polymarket обязали раскрыть KYC/geo-blocking processes. Risk: усиление мандатных KYC для всех пользователей в ближайшие месяцы.

7. **Источник для нескольких ключевых latency-цифр — TradoxVPS, QuantVPS, TradingVPS блогов** — у этих ресурсов очевидная коммерческая мотивация продавать VPS. Где возможно, я отметил независимые источники (Polymarket docs, CoinDesk, Finance Magnates), но часть latency-измерений (Dublin 5ms / Amsterdam 10ms) — единственно от VPS-провайдеров. Проверь сам через `ping` / `mtr` от своей выбранной локации до `clob.polymarket.com` до того, как платить.

8. **Critical date discrepancy:** ты в задании указал **22 апреля 2026** как дату CTF v2 launch. Точная дата по официальной Polymarket-документации — **28 апреля 2026** в ~11:00 UTC. Все мои данные собраны с пост-28-апреля периода (некоторые конкретные подтверждения цифр о spread compression и opportunity duration — из исследования IMDEA Networks за окно до этого, но они описывают тренд, который только усилился пост-V2).