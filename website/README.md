# Сайт Энергостора

Рабочая ветка сайта — `website`. Состояние исходников и темы OpenCart на 5 ноября 2026 года.

- `energostor/` — текущая витрина, главная, каталог, бренды, вендоры и изображения.
- `energostor/assets/css/` — общие стили и подключение Medeo.
- `energostor/assets/catalog/` — интерфейс каталога и клиент API.
- `energostor/assets/js/navigation.js` — меню категорий.
- `energostor/backend/` — приватный Python-сервис каталога и его тесты. Эту папку нельзя публиковать как статику.
- `opencart/upload/` — файлы оформления, которые накладываются на установленный OpenCart 4.1.0.4. Главная находится в `catalog/view/template/common/home.twig`, оформление остальных страниц в `energostor-theme/native.css`.

## Работа с другого компьютера

```powershell
git clone --branch website --single-branch https://github.com/starosvetsky/ESPBS.git ESPBS-website
cd ESPBS-website
git pull --ff-only
```

После правок выполните `git add website`, `git commit` и `git push origin website`.

Для локального просмотра статических страниц из корня репозитория выполните `python -m http.server 8080 --directory website/energostor`. Главная откроется по `http://localhost:8080/`. Каталог требует подключения к API. Для просмотра текущих серверных данных можно временно задать в `website/energostor/assets/catalog/config.js` значение `apiBase: 'https://starosvetsky.ru/energostor/api/catalog'`.

## Что сейчас развёрнуто

Текущая витрина находится на `https://starosvetsky.ru/energostor/`. OpenCart с отдельным входом для просмотра — на `https://starosvetsky.ru/energostor-opencart/`.

Git push сохраняет исходники в GitHub. Автоматический деплой этой ветки не настроен. Файлы OpenCart размещаются в `/opt/energostor-opencart/upload/`, статическая витрина — в `/var/www/starosvetsky.ru/energostor/`. Перед публикацией сохраняйте резервную копию изменяемых файлов. У OpenCart общие ресурсы продублированы в `opencart/upload/energostor-theme/assets/`, поэтому соответствующие изменения нужно переносить в обе версии. OpenCart использует отдельный адаптер `navigation.js`, который формирует ссылки на его категории.

Перенос на OpenCart продолжается. На главной перенесено оформление, в каталоге установлены товары, бренды и категории. Изображения товаров, характеристики, документы и автоматическое обновление ассортимента ещё требуют интеграции. Названия разделов меню и их ссылки записаны в снимке `energostor-theme/catalog-data.js`.

## Ограничения публикации

Базы, пароли, конфигурации OpenCart с доступом к БД, серверные журналы и пользовательские данные отсутствуют в этой папке. Полный движок OpenCart устанавливается отдельно из официального релиза. Шрифт интерфейса — Medeo Sans, моноширинный текст — Medeo Mono. Вес шрифта не выше 500, межбуквенное расстояние обычное.
