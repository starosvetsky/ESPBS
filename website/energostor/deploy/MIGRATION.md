# Переезд на energostor.ru

Сайт и каталог могут работать на том же сервере, что и ESPBS. Публичный сайт
использует nginx и файлы в `/var/www/energostor.ru`; каталог остаётся отдельным
loopback-сервисом на `127.0.0.1:8766`; парсер продолжает слушать `127.0.0.1:8765`.
Второй worker ESPBS и вторая копия его рабочей базы не запускаются.

## До переключения DNS

1. Проверить `df -h`, `free -h`, активные задания ESPBS и состояние сервисов.
2. Сделать резервные копии nginx, `/var/www/energostor.ru` (если существует),
   `/opt/energostor-catalog` и `/var/lib/energostor-catalog`.
3. Собрать архив: `python website/energostor/tools/package_production.py`.
4. Распаковать архив в staging, сверить SHA-256 по manifest и только затем
   атомарно заменить web root.
5. Установить `energostor.ru.http.conf`, выполнить `nginx -t` и reload.
6. Направить A-записи `energostor.ru` и `www.energostor.ru` на `136.234.4.214`.

## HTTPS и приёмка

После обновления DNS выпустить сертификат Certbot, заменить HTTP-конфигурацию на
`energostor.ru.https.conf`, снова выполнить `nginx -t` и reload. Проверить:

- главную, `/catalog/`, `/brands/`, `/vendors/` и статические ресурсы;
- `/api/catalog/api/meta` и поиск по точному артикулу;
- форму реальной заявкой: наличие JSON-ответа не доказывает доставку письма;
- редиректы HTTP → HTTPS и `www` → основной домен;
- `systemctl is-active energostor-catalog espbs` и таймер обновления каталога;
- что тестовый `/energostor/` на старом домене и `/espbs/` не изменились.

DNS переключается только после локальной проверки через временную запись hosts
или `curl --resolve`. Старый сайт не удаляется до завершения приёмки и отдельного
решения о редиректе.
