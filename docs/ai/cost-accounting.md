# AI cost accounting

**Implemented and tested with a fake provider. No real AI provider has ever been called**, because no API key is configured. The OpenAI adapter has only been run against simulated HTTP responses shaped like the documentation.

## Using the gateway

All AI goes through `apps.ai_gateway.gateway.execute(AIRequest(...))`. A test fails if any other module imports a provider SDK. The API key is held only by the `worker` service.

The gateway refuses to run inside a transaction. Its reservation must commit before the provider call, so concurrent requests see it, and no row lock may be held during a slow network call. Call it from a task based on `UnscopedTenantTask`.

## What happens on a request

1. Check tenant membership, tenant status and the capability required by the operation.
2. Check the policy: operation and model must both be in the plan. No policy means no AI.
3. Check the model is active, a price is in force, and an active prompt version exists.
4. Reject any variable the operation does not declare, and any input over its size limit.
5. Calculate the maximum possible cost, and reject it if over the per-request cap.
6. Apply the per-minute rate limit. This fails closed if Redis is down.
7. Serve from the tenant's own cache if the operation allows it.
8. Lock the tenant's budget row, check firm and user limits, and commit a reservation.
9. Call the provider, outside any transaction.
10. Commit the actual cost and release the rest, or follow the failure rules below.

## How concurrency is enforced

The budget row for the billing period is locked with `SELECT ... FOR UPDATE` while each reservation is checked and written, so reservations of one tenant are serialised. Removing that lock made 3 of the 4 concurrency tests fail in a mutation run.

## Maximum cost

Tokens cannot be counted exactly before a call, so the bound assumes one token per UTF-8 byte of input, at the dearest input rate, plus the maximum output. This overestimates considerably. As a result, the hard stop acts before a budget is fully used: near the limit, a request whose worst case does not fit is refused even if its real cost would have fitted.

## Calculating actual cost

Per the OpenAI prompt caching guide, `cached_tokens` and `cache_write_tokens` are parts of `input_tokens`, each with its own rate:

```
ordinary = input - cached - write_30m - write_12h
cost = (ordinary × input rate + cached × read rate + write_30m × 30m rate
        + write_12h × 12h rate + output × output rate) / 1,000,000
```

A test reproduces the guide's worked example, $0.01515. Costs use `Decimal` and round up at 8 decimal places. Cache writes reported without a lifetime split are priced at the dearer 12-hour rate.

## Failure rules

| Outcome | Reservation | Budget effect |
|---|---|---|
| Success | Committed | Actual cost |
| Usage not reported | Committed | The full maximum |
| Refused, incomplete or invalid output | Committed, answer not returned | Actual cost |
| 4xx, or no API key | Released | None |
| 429 | Retried at most twice with backoff, then released | None |
| Timeout, dropped connection, 5xx, any unexpected error | `unknown` | Stays held |
| Process dies mid-call | Stays `reserved` | Stays held |

Held money leaves only through `/platform/ai/` once staff have checked the provider's records, and every such resolution is audited. A running reservation becomes eligible after one hour.

## Database enforcement

- The application cannot write policies, and it cannot change budget limits. Inserted budget rows always take their limits from the policy, through a trigger.
- Prices, prompt text and usage events are immutable, even for the owner.
- `AIUsageEvent` holds no prompt or answer.
- Stored answers are tenant-isolated, cannot be updated by the application, and expire after 7 days, or at the operation's cache lifetime.
- Cache keys include the tenant, so caches are never shared.

## Setting up a real provider

Prices must come from the provider's official price list. None are bundled, because a remembered price would be wrong sooner or later.

```powershell
docker compose run --rm migrate python manage.py set_ai_model_price --provider openai --model <name> --input <n> --cached-read <n> --cache-write-30m <n> --cache-write-12h <n> --output <n> --currency USD --effective-from <ISO date> --source-url <official page>
```

Then point an operation's `default_model` at the model, put `OPENAI_API_KEY` in `.env`, and enable the firm in `/platform/ai/`. Assigning a model to an operation has no command yet, except for the development seed.

## Development

`docker compose run --rm migrate python manage.py seed_ai_dev` installs a fake provider with invented prices and enables it for the demo firm, and it refuses to run unless the fake provider is allowed. Fake answers are marked `is_synthetic` and labelled on every page. Production settings do not allow the fake provider.

## Not built yet

- A first real provider call.
- GBP and RON reporting. The `AIExchangeRate` table exists but has no way to enter rates and no pages use it, so costs appear in USD only.
- Contribution margin, which needs revenue from Milestone 7.
- Email for budget alerts. They appear on the firm's AI page only.
- Semantic caching. Only exact-match caching exists.
- A provider adapter other than OpenAI.
- Automatic reconciliation. Staff enter the provider's figure by hand.
