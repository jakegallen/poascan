## 1. Halt list

| Endpoint | Pressure | Live latency | Status |
|---|---|---|---|
| `GET/POST /api/hosted/answer` | - | - | ⏳ halt |
| `GET/POST /api/hosted/grade` | - | - | ⏳ halt |
| `GET /api/hosted/challenge` | - | - | ⏳ halt |
| `GET /api/hosted/me` | - | - | ⏳ halt |
| `GET/POST /api/hosted/mine` | - | - | ⏳ halt |
| `GET/POST /api/hosted/register` | - | - | ⏳ halt |
| `GET /api/hosted/assignments` + `/api/assignments/:addr` | - | - | ⏳ halt |
| **JOIN family**: `/api/join-connected`, `/j/<token>`, `/api/link-auto`, `/api/link-signed`, `/api/hosted/adopt` | - | - | ⏳ halt |
| `/a/<cred>/*` path-actions | - | - | ⏳ halt |
| `/mcp` mining tools | - | - | ⏳ halt |

**Stays live:** `/api/status` · explorer + settlement · `POST /api/submit` + `/api/receipt/:txid` · swaps reads

## 2. Next
