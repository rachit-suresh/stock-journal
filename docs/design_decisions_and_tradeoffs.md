# Comprehensive System Design, Architecture Options & Engineering Tradeoffs

**Project:** Real-Time Indian Stock Market Journal Application  
**Target Execution Environment:** Decoupled Architecture (Stateless Edge UI/API + Stateful Always-On Background Worker / Monolith Engine)  
**Primary Exchange Target:** NSE/BSE Equity Markets  

---

## 1. Executive Context & Problem Statement

The objective is to build a high-performance, real-time stock journal application for tracking Indian equity positions (NSE/BSE) with live Last Traded Price (LTP) updates every few seconds.

The primary architectural constraint is delivering low-cost or zero-cost real-time streaming market feeds to a pre-built frontend UI while keeping operational infrastructure overhead minimal, secure, and compliant with broker rate limits and exchange guidelines.

---

## 2. Market Data Provider Evaluation Matrix

Polling standard REST APIs for ticker updates across Indian stock exchanges is non-viable due to TCP handshake overhead, rate-limiting HTTP status codes (`429 Too Many Requests`), and IP blocking by exchange Web Application Firewalls (WAFs) like Akamai. Live tick delivery requires streaming WebSocket feeds.

### Comparative Analysis of Indian Broker & Data APIs

| Provider | Transport Protocol | Pricing Model | Latency | Key Technical & Operational Characteristics |
| --- | --- | --- | --- | --- |
| **Angel One SmartAPI** | WebSocket 2.0 (`wss://`) & REST | **₹0 / month** | Sub-second | **Primary Choice.** Direct JSON/binary stream. Free access to live feeds, historical data, and SDKs across Equity and F&O. |
| **Upstox API v3** | WebSocket & REST | **₹0 / month** | Sub-second | Native **Protocol Buffer (Protobuf)** binary serialization. Drastically reduces network payload size compared to JSON. |
| **DhanHQ Data API** | WebSocket & REST | **₹499 / month** (+ GST) | Tick-by-tick | Enterprise reliability; supports Level 3 (20-depth order book) streaming capabilities. |
| **Zerodha Kite Connect** | Binary WebSocket Ticker & REST | **₹500 / month** | Sub-second | Industry-standard developer stability, but mandates a fixed monthly subscription even for read-only ticker usage. |
| **nsepython / Web Scraping** | REST Polling | **₹0 / month** | 3s–15s | Reverse-engineered internal NSE endpoints. High risk of immediate IP bans by Akamai WAF. |
| **yfinance / Yahoo Finance** | REST Polling | **₹0 / month** | **15-min Delayed** | Market data for NSE (`.NS` tickers) is delayed by 15 minutes; completely unusable for real-time tracking. |

---

## 3. Downstream Architecture Options & Tradeoff Critique

Evaluating real-time market data delivery requires decoupling three distinct lifecycle layers:

1. **Ingestion Layer (Upstream):** Broker Connection $\rightarrow$ Ingestion Worker
2. **State Management Layer (Cache):** In-Memory Store / Key-Value Cache
3. **Egress Layer (Downstream Transport):** Backend $\rightarrow$ Client App / Browser UI

```
[Broker WS Engine] ===> [Ingestion Layer] ===> [State Storage] ===> [Egress Transport] ===> [Client UI]
```

---

### Option 1: Direct WebSocket Connection from Client to Broker

```
[Broker WS Engine] <====== (wss:// Direct) ======> [Client App / Browser]
```

* **Mechanism:** The browser establishes a direct WebSocket connection to Angel One / Upstox using broker client credentials.
* **Critique (CRITICAL FAULT - Anti-Pattern):**
  * **Credential Exposure:** Broker secret keys, API tokens, and JWTs must be shipped to the client browser, permitting total account compromise via simple asset reverse-engineering.
  * **Upstream Hard Connection Limits:** Brokers enforce strict limits on concurrent WebSocket sessions per API key (typically 1 to 5 connections). Multiple open tabs trigger rate-limit disconnects.
  * **UI Thread Starvation:** Unfiltered raw market feeds push 10–50 ticks/second during high volatility, overwhelming client-side single-threaded event loops.

---

### Option 2: Server-Mediated WebSocket Proxy

```
[Broker WS] ===> [Ingestion Server] ===> (WebSocket) ===> [Client App]
```

* **Mechanism:** The backend ingests the broker feed and proxies ticks directly down to connected clients over a custom WebSocket server.
* **Critique (SUB-OPTIMAL):**
  * **Solves Security & Fan-In:** Safely abstracts broker credentials and multiplexes $N$ downstream clients into 1 upstream socket.
  * **The "Cold Start" Flaw:** Operates as a stateless pass-through pipe. When a user connects or refreshes, the UI remains completely blank until the *next tick* arrives. For illiquid instruments, this delay can last minutes.
  * **Unnecessary Full-Duplex Overhead:** WebSockets maintain bidirectional TCP buffers, requiring custom application-level heartbeat frames (`ping`/`pong`), masking logic, and custom client reconnect state machines for a stream that is 100% unidirectional (Server $\rightarrow$ Client).

---

### Option 3: In-Memory Cache + Downstream WebSocket Engine

```
[Broker WS] ===> [Ingestion Server] ===> [Redis In-Memory] 
                                                ||
                                         [Push WS Engine] ===> [Client App]
```

* **Mechanism:** Ticks overwrite an in-memory store. When a client connects, an initial state snapshot is fetched, followed by live delta updates via a downstream WebSocket.
* **Critique (OVER-ENGINEERED):**
  * **Solves Cold-Start:** Initial `MGET` against cache hydrates the UI in 0ms.
  * **Protocol Overhead:** Still mandates maintaining complex persistent socket server state downstream, requiring custom connection-resumption logic, exponential backoff with jitter, and frame-parsing infrastructure on both client and server.

---

### Option 4: In-Memory Cache + Downstream Server-Sent Events (SSE)

```
[Broker WS] ===> [Ingestion Server] ===> [Redis In-Memory] 
                                                ||
                                         [SSE Controller] ===> [Client App]
```

* **Mechanism:** Upstream ticks update an in-memory cache. The server pushes updates downstream using a persistent, HTTP-native `text/event-stream` (SSE).
* **Critique (OPTIMAL FOR TRADITIONAL ALWAYS-ON SERVERS):**
  * **Protocol Alignment:** SSE natively enforces unidirectional push over HTTP/1.1 or HTTP/2, perfectly matching market ticker semantics.
  * **Native Resiliency:** Browsers automatically manage connection drops and retries via the `EventSource` API using `Last-Event-ID` tracking without custom client JavaScript.
  * **Server Constraints:** Requires an **always-on, stateful server** (e.g., FastAPI, Node.js, Go Docker on Render/DigitalOcean) to hold TCP socket file descriptors open without process execution timeouts.

---

### Option 5: Redis Pub/Sub Fan-Out Architecture (Horizontally Scalable)

```
                  +--------------------------+
                  | Ingestion Worker (Node/Go)|
                  +------------+-------------+
                               | Ticks
               +---------------v---------------+
               |   Redis Cache + Pub/Sub Bus   |
               +-------+---------------+-------+
                       |               |
         +-------------v-+           +-v-------------+
         | SSE Gateway 1 |           | SSE Gateway 2 |
         +-------+-------+           +-------+-------+
                 |                           |
         +-------v-------+           +-------v-------+
         | Client A, B   |           | Client C, D   |
         +---------------+           +---------------+
```

* **Mechanism:** Decouples ingestion from distribution. The ingestion worker writes ticks to Redis state (`SET stock:3045:ltp 580.20`) and broadcasts them to a pub/sub channel (`PUBLISH ticks:3045 580.20`). Independent, stateless API gateways subscribe to channels and fan out SSE feeds to client clusters.
* **Single-Server Optimization:** If the entire system runs on a single process (FastAPI Monolith), Redis Pub/Sub and Redis Caching are replaced with native language primitives:
  * **In-Memory Cache:** Thread-safe `PriceCache` (`threading.Lock` + `Dict[str, float]`).
  * **Internal Event Bus:** `asyncio.Queue` or shared memory thread cache.

---

### Option 6: Cache-Backed SWR (Stale-While-Revalidate) Polling

```
[Broker WS] ===> [Ingestion Worker] ===> [Redis State Store] 
                                                ^
[Client UI] === (HTTP GET /api/prices) ======== | (Polls every 3–5 seconds)
```

* **Mechanism:** The backend maintains a cache populated by an upstream WebSocket worker. The client UI polls a stateless REST API endpoint every 3–5 seconds using SWR client caching (RFC 5861).
* **Critique (OPTIMAL FOR STATELESS/SERVERLESS PLATFORMS LIKE VERCEL):**
  * **Stateless Scaling:** Every poll is a standard short-lived HTTP `GET` request.
  * **Connection Leak Prevention:** SWR automatically halts polling when the browser tab loses focus (`revalidateOnFocus`), preventing background server load.
  * **Serverless Compatibility:** Eliminates open socket connection costs and execution duration limits on serverless platforms.

---

## 4. The Serverless Paradigm Shift: Why Polling is the Correct Pattern on Vercel

While polling is traditionally considered an anti-pattern due to empty polls, HTTP header overhead, and $T/2$ bound latency, **deploying on serverless platforms (Vercel) completely inverts this trade-off.**

```
STATEFUL ENGINE (VPS):     [Server Always On]  <=== (1 Open Connection for 6 Hours) ===> Client
                           Cost: $0 extra. Socket held in memory.

SERVERLESS ENGINE (Vercel): [Client Poll] ===> [Function Wakes] === (10ms Cache Read) ===> [Function Dies]
                           Cost: Fractional pennies. Function execution time near zero.
```

### The Physical Constraints of Serverless Execution:

1. **Strict Function Duration Limits:**
   * Vercel Functions enforce default maximum duration limits (e.g., 10–15 seconds on Hobby plans, configurable up to 300s/1800s on Pro/Enterprise plans).
   * Holding an SSE connection or WebSocket open inside a serverless function causes Vercel to forcibly terminate the execution process, resulting in constant client drops and endless TCP/TLS handshake loops.
2. **Execution Billing (GB-Seconds):**
   * Serverless billing is calculated as $\text{Memory Allocated} \times \text{Execution Duration}$.
   * Holding persistent sockets open for 1,000 active users for 1 hour bills 1,000 hours of continuous function execution time.
   * With SWR polling, a function wakes up, queries the cache in 10ms, returns JSON, and terminates immediately—keeping active execution time near zero.

---

## 5. Upstream Data Ingestion Pipeline & Broker Authentication

Because serverless platforms cannot run long-lived processes, **the Ingestion Worker must be decoupled from the Vercel Frontend.**

```
+-----------------------------------------------------------------------------------+
|  1. INGESTION WORKER (Always-On Stateful Process)                                 |
|  (Hosted on Render / Railway / Fly.io as Docker container)                        |
|  - Holds WebSocket 2.0 connection to Angel One SmartAPI                           |
|  - Decodes real-time market ticks                                                 |
|  - Writes ticks directly to Upstash Redis or In-Memory Cache                      |
+----------------------------------------+------------------------------------------+
                                         | Writes (SET stock:3045:ltp 580.20)
                         +---------------+---------------+
                         |      State Cache Layer       |
                         +---------------+---------------+
                                         ^ Reads (MGET /api/prices)
+----------------------------------------+------------------------------------------+
|  2. VERCEL FRONTEND & API GATEWAY (Stateless Serverless)                         |
|  - Client UI executes SWR polling (GET /api/prices?tokens=3045,2885) every 3s    |
|  - Vercel Function reads Cache over HTTP pipeline, returns JSON, and dies         |
+-----------------------------------------------------------------------------------+
```

### SmartAPI Daily Authentication Handshake Sequence

1. **Programmatic TOTP Generation:** Local Process.  
   Pass the saved TOTP secret key into `pyotp.TOTP(SECRET_KEY).now()` to obtain a live 6-digit 2FA token.
2. **Authenticate Session:** REST `POST /rest/auth/angelbroking/user/v1/loginByPassword`.  
   Send `clientcode`, `password`, `api_key`, and `totp` to generate a 24-hour `jwtToken` and `feedToken`.
3. **Establish WebSocket 2.0 Connection:** `wss://smartapisocket.angelone.in/smart-stream`.  
   Initialize `SmartWebSocketV2` passing `jwtToken`, `apiKey`, `clientCode`, and `feedToken` in connection headers.
4. **Subscribe to Tokens:** Subscription Mode 1 (LTP).  
   Dispatch subscription JSON for specified instrument tokens (e.g., Token `3045` for SBIN-EQ, Token `2885` for PNB-EQ).

---

## 6. Containerization & Deployment Strategy

### Is Blind Containerization (Docker Everywhere) Good Practice?

**No. Containerizing every project indiscriminately is a software engineering anti-pattern (Premature Abstraction / Cargo Culting).**

Vercel natively supports deploying custom OCI images via `Dockerfile.vercel`, but it executes those images on its **Fluid Compute serverless infrastructure**, retaining all serverless execution duration and memory constraints. Adding Docker to standard Next.js Vercel routes simply bloats CI/CD build pipelines without turning Vercel into an always-on server.

### Component Deployment Strategy

```
+-----------------------------------------------------------------------------------+
| COMPONENT                  | PLATFORM   | DOCKER USAGE? | RATIONALE               |
+----------------------------+------------+---------------+-------------------------+
| Next.js Frontend & API     | Vercel     | NO (Skip)     | Native deployment       |
|                            |            |               | offers faster builds &  |
|                            |            |               | zero registry overhead. |
+----------------------------+------------+---------------+-------------------------+
| SmartAPI Ingestion Worker  | Render /   | YES (Use)     | Locks Python runtime,   |
|                            | Railway    |               | `pyotp`, and `redis`    |
|                            |            |               | dependencies for 24/7   |
|                            |            |               | execution.              |
+----------------------------+------------+---------------+-------------------------+
```

---

## 7. Micro-Level Code Mechanics & Micro Design Decisions

### 7.1 Data Validation: Pydantic v2 Models vs. Python Dataclasses / Plain Dicts

#### **Context & Decision**
We selected **Pydantic v2 (`BaseModel`)** for data models in `app/models/` (`TradeCreate`, `TradeUpdate`, `TradeResponse`, `StrategyCreate`, `EmotionCreate`).

#### **Alternatives Evaluated**
1. **Option A: Plain Python Dictionaries**
2. **Option B: Standard Python `@dataclass`**
3. **Option C: Pydantic v2 `BaseModel`** — *Selected*

#### **Evaluation & Comparison**

| Criteria | Plain Dicts | Python `@dataclass` | Pydantic v2 `BaseModel` |
| :--- | :--- | :--- | :--- |
| **Runtime Type Validation** | None (Manually parse & check keys) | None (Requires `typeguard` package) | **Built-in Rust-backed `pydantic-core` validation** |
| **HTTP Body Integration** | Manual JSON parsing | Manual deserialization | **Automatic FastAPI OpenAPI schema generation & 422 errors** |
| **Field Constraints** | Manual `if price <= 0:` logic | Manual `__post_init__` checks | **Declarative `Field(..., gt=0)` constraints** |
| **Serialization** | `json.dumps()` | `dataclasses.asdict()` | **`model_dump()` / `model_dump_json()`** |

#### **Technical Rationale & Trade-offs**
- **Trade-off**: Slightly higher CPU overhead during module initialization compared to plain dicts.
- **Benefit**: Pydantic v2 runs validation in compiled Rust (`pydantic-core`), executing 5x–20x faster than Pydantic v1. It eliminates defensive manual type-checking code inside API endpoint functions.

---

### 7.2 Thread Concurrency & Synchronization: `threading.Lock` vs. `asyncio.Lock` / Redis

#### **Context & Decision**
In `app/streaming/price_cache.py`, the `PriceCache` uses a standard **`threading.Lock()`** to guard price updates in `_prices: Dict[str, float]`.

#### **Alternatives Evaluated**
1. **Option A: `asyncio.Lock`**
2. **Option B: Distributed Redis Key-Value Store**
3. **Option C: Python `threading.Lock()`** — *Selected*

#### **Technical Rationale & Trade-offs**
- **Why NOT `asyncio.Lock`?**  
  The market streamer (`AngelOneSmartApiStreamer` / `MockMarketStreamer`) runs in a separate **synchronous OS daemon thread** to isolate WebSocket callbacks. An `asyncio.Lock` is bound to a single asyncio event loop thread; attempting to acquire an `asyncio.Lock` from an OS worker thread throws `RuntimeError: There is no current event loop in thread`.
- **Why NOT Redis?**  
  Redis requires inter-process network calls (TCP sockets / HTTP requests), introducing 1–10 ms latency per tick update.
- **Why `threading.Lock()`?**  
  `threading.Lock()` provides thread safety between the background OS streamer thread (updating prices) and the asyncio event loop thread (reading prices for `/api/prices`), executing in **sub-microsecond** time.

---

### 7.3 Asynchronous Non-Blocking I/O: Motor Driver vs. Sync PyMongo

#### **Context & Decision**
In `app/core/database.py` and `app/repositories/mongo/`, we utilized **Motor (`AsyncIOMotorClient`)** rather than standard `pymongo`.

#### **Technical Rationale & Performance Impact**
FastAPI operates on an asynchronous event loop powered by `uvicorn` and `anyio`.
- When a synchronous `pymongo` call is executed inside an `async def` route function, python blocks the single event loop thread while waiting for database socket I/O. During this wait, **all other concurrent client HTTP requests are queued**.
- Motor wraps PyMongo using `asyncio`, yielding control back to the event loop during MongoDB network wait times. This allows the server to process hundreds of concurrent HTTP requests without increasing thread counts.

---

## 8. Low-Level Subsystem Design Decisions

### 8.1 Persistence Abstraction: Repository Pattern & Interface Contracts (DIP)

#### **Context & Decision**
We established abstract interfaces (`ITradeRepository`, `IStrategyRepository`, `IEmotionRepository`) in `app/repositories/interfaces/` using Python's `abc.ABC`.

```python
class ITradeRepository(ABC):
    @abstractmethod
    async def get_all_trades(self) -> List[dict]: pass
```

#### **Alternatives Evaluated**
Directly instantiating `db["trades"]` inside FastAPI endpoints or `JournalService`.

#### **Technical Rationale & Trade-offs**
- **Trade-off**: Requires writing interface abstract classes and maintaining concrete implementations (additional files).
- **Benefit**: Achieves complete **Dependency Inversion**. If business requirements change in the future (e.g., migrating to PostgreSQL or Redis), we only implement a `SqlTradeRepository` adhering to `ITradeRepository`. **Zero lines of API route handlers or service logic will change.**

---

### 8.2 Cascading Trade Reassignment on Category Deletion

#### **Context & Decision**
In `MongoStrategyRepository.delete_strategy(name)` and `MongoEmotionRepository.delete_emotion(name)`, deleting a strategy or emotion automatically executes an `update_many` operation on the `trades` collection.

```python
await self.trades_collection.update_many(
    {"strategy": actual_name},
    {"$set": {"strategy": "Uncategorized"}}
)
```

#### **Alternatives Evaluated**
1. **Option A: Hard Delete Linked Trades**: Deletes any trade that referenced the deleted strategy. (*Unacceptable — causes severe trader financial log data loss*).
2. **Option B: Block Deletion**: Throws an error if any trade references the strategy. (*Poor UX*).
3. **Option C: Soft Cascade Reassignment**: Removes the strategy tag document and reassigns all affected trades to `"Uncategorized"` / `"Neutral"`. — *Selected*

#### **Technical Rationale**
Preserves historical trade log entries, metrics, entry prices, and financial loss calculations intact while allowing the trader to trim obsolete strategy names.

---

## 9. System Topology & LLD Principles (SOLID Breakdown)

The application design adheres to **SOLID design principles**:

1. **Single Responsibility Principle (SRP):**  
   - `MongoTradeRepository`: Responsible exclusively for MongoDB trade collection queries.  
   - `JournalService`: Responsible solely for business orchestration and initial database seeding.  
   - `PriceCache`: Responsible strictly for thread-safe in-memory tick storage.  
   - `AngelOneSmartApiStreamer`: Handles WebSocket connections and binary tick parsing only.
2. **Open/Closed Principle (OCP) & Strategy Pattern:**  
   - Upstream market data ingestion depends on an abstract base class (`IMarketDataStreamer`). Switching from `AngelOneSmartApiStreamer` to `UpstoxStreamer` or `ZerodhaStreamer` requires zero structural code modifications to downstream cache or API layers.
   - Storage repositories depend on abstract interfaces (`ITradeRepository`), allowing database engine additions without modifying route handlers.
3. **Liskov Substitution Principle (LSP):**  
   - Both `AngelOneSmartApiStreamer` and `MockMarketStreamer` are fully interchangeable instances of `IMarketDataStreamer`.
4. **Interface Segregation Principle (ISP):**  
   - Granular, focused repository interfaces (`ITradeRepository`, `IStrategyRepository`, `IEmotionRepository`) instead of one monolithic database interface.
5. **Dependency Inversion Principle (DIP):**  
   - `JournalService` and API route functions depend on abstractions (`ITradeRepository`), never concrete low-level MongoDB driver implementations. Dependencies are injected via FastAPI's `Depends()`.

---

## 10. Master Summary of Architectural Trade-offs

| Architectural Decision | Alternative Considered | Accepted Trade-off | Key Advantage Gained |
| :--- | :--- | :--- | :--- |
| **FastAPI Monolith** | Microservices Architecture | Single container RAM ceiling | Zero inter-service network latency, 1-click cloud deployment. |
| **Async Motor Driver** | Sync PyMongo Driver | Requires `async/await` syntax throughout repository classes | Non-blocking event loop execution under high request concurrency. |
| **Repository Pattern (DIP)** | Direct MongoDB queries in routes | Extra interface classes & abstract methods | Total database engine independence (MongoDB, SQL, Redis interchangeable). |
| **Thread-Safe `PriceCache`** | External Redis Cache | Prices exist in RAM (reset on process restart) | Microsecond read speeds without cloud cache costs or network hops. |
| **Pydantic v2 Models** | Plain Python Dicts | Minor CPU initialization overhead | Rust-accelerated type validation & automatic OpenAPI schema docs. |

---

## 11. Technical Glossary

* **LTP (Last Traded Price):** The execution price of the most recent transaction on the exchange matching engine.
* **SWR (Stale-While-Revalidate):** An HTTP cache invalidation strategy defined in RFC 5861 that returns cached data immediately while asynchronously revalidating in the background.
* **Protobuf (Protocol Buffers):** Google's language-neutral binary serialization mechanism designed to compress structured data for low-latency transmission.
* **Server-Sent Events (SSE):** A client-server transport mechanism enabling a server to push real-time text updates to a browser over standard HTTP.
* **Upstash Redis:** A serverless-native, HTTP-based Redis database that allows short-lived cloud functions to perform pipeline reads without maintaining persistent TCP connection pools.
* **TOTP (Time-based One-Time Password):** A temporary 6-digit passcode generated algorithmically using a shared secret key and the current system timestamp (RFC 6238).
* **Cargo Culting:** The uncritical adoption of software practices or tools (e.g., containerizing every app indiscriminately) without understanding the underlying technical trade-offs.
