# Источники комплекта

Подготовлено 23 октября 2026. Это сокращённые русскоязычные адаптации идей и инструкций; внешние плагины и исполняемые скрипты не устанавливались. Адаптации сохраняют unittest и правила ESPBS, не вводят обязательный процент покрытия, чужие модели, context manager, hooks или новые зависимости. Обновлять их следует осознанно по diff, а не автоматически заменять upstream-файлами.

| Источник и зафиксированная ревизия | Использование |
| --- | --- |
| [obra/superpowers](https://github.com/obra/superpowers/tree/2ce8aa15d05bd57213e6f746f953aafb7ded7a8b), `skills/systematic-debugging/SKILL.md`, `skills/verification-before-completion/SKILL.md` | espbs-debugging, espbs-verification |
| [wshobson/agents](https://github.com/wshobson/agents/tree/0874a27b17a22e2b7c2e2bcd725768e0803cad06), `plugins/python-development/skills/python-testing-patterns/SKILL.md`, `python-performance-optimization/SKILL.md`, `plugins/python-development/agents/python-pro.md` | espbs-testing, espbs-performance, роль espbs-python |
| [VoltAgent/awesome-claude-code-subagents](https://github.com/VoltAgent/awesome-claude-code-subagents/tree/408d3c9eee2d0c75c12a3abb5de29e53c2ca6b9e), `categories/04-quality-security/qa-expert.md`, `code-reviewer.md` | роли espbs-qa и espbs-reviewer |

Полные тексты MIT-лицензий сохранены в `licenses/` рядом с этим файлом. espbs-data-integrity написан по локальным правилам и архитектуре ESPBS.

Формат проектных ролей и скиллов сверялся с [Subagents](https://learn.chatgpt.com/docs/agent-configuration/subagents) и [Build skills](https://learn.chatgpt.com/docs/build-skills). Загрузка в конкретном клиенте требует отдельной проверки.

Playwright не включён: это дополнительная настройка браузерного окружения, не необходимая для текущего этапа хранения. При задачах панели используй уже доступные браузерные инструменты или отдельно подключи подходящий скилл.
