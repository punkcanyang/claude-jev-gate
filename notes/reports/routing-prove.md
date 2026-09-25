# 路由证明（claude-jev-gate）

- 样本数：20
- 硬一致：20/20 = 100.0%
- 选型分布：{'cheap': 5, 'complex': 5, 'tool_heavy': 5, 'long_context': 5}
- 关路由 labels：['primary']
- failures：none

| id | bucket | expect | got | model | conf | fallback | match |
|---|---|---|---|---|---|---|---|
| s01 | simple | cheap | cheap | `deepseek-chat` | 0.72 | False | Y |
| s02 | simple | cheap | cheap | `deepseek-chat` | 0.72 | False | Y |
| s03 | simple | cheap | cheap | `deepseek-chat` | 0.72 | False | Y |
| s04 | simple | cheap | cheap | `deepseek-chat` | 0.72 | False | Y |
| s05 | simple | cheap | cheap | `deepseek-chat` | 0.72 | False | Y |
| c01 | complex | complex | complex | `deepseek-reasoner` | 0.72 | False | Y |
| c02 | complex | complex | complex | `deepseek-reasoner` | 0.72 | False | Y |
| c03 | complex | complex | complex | `deepseek-reasoner` | 0.72 | False | Y |
| c04 | complex | complex | complex | `deepseek-reasoner` | 0.72 | False | Y |
| c05 | complex | complex | complex | `deepseek-reasoner` | 0.72 | False | Y |
| t01 | tool-heavy | tool_heavy | tool_heavy | `deepseek-reasoner` | 0.72 | False | Y |
| t02 | tool-heavy | tool_heavy | tool_heavy | `deepseek-reasoner` | 0.72 | False | Y |
| t03 | tool-heavy | tool_heavy | tool_heavy | `deepseek-reasoner` | 0.72 | False | Y |
| t04 | tool-heavy | tool_heavy | tool_heavy | `deepseek-reasoner` | 0.72 | False | Y |
| t05 | tool-heavy | tool_heavy | tool_heavy | `deepseek-reasoner` | 0.72 | False | Y |
| l01 | long-context | long_context | long_context | `deepseek-reasoner` | 0.72 | False | Y |
| l02 | long-context | long_context | long_context | `deepseek-reasoner` | 0.72 | False | Y |
| l03 | long-context | long_context | long_context | `deepseek-reasoner` | 0.72 | False | Y |
| l04 | long-context | long_context | long_context | `deepseek-reasoner` | 0.72 | False | Y |
| l05 | long-context | long_context | long_context | `deepseek-reasoner` | 0.72 | False | Y |
