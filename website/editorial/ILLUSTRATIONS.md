# Иллюстрации журнала

Для всех 25 существующих публикаций созданы отдельные тематические обложки
встроенным image_gen. Стиль: реалистичная промышленная фотография, холодная
сине-серая палитра и локальные крупные полупрозрачные пиксели по краям,
по образцу ind-industry.webp с главной. Не пиксель-арт.

Промпты: «Editorial industrial photograph for engineering journal about
[тема соответствующего материала]. Landscape 3:2. Photorealistic neutral
technical equipment, no brands, logos, readable text, people or unsafe wiring.
Sharp central subject, cool restrained blue grey light. Localized coarse
square pixel mosaic patches along edges fading into the photograph, matching
Energostor homepage visual identity. Not pixel art.»
Для первой обложки использован сюжет инженера у щита и конфигурации на ноутбуке.

WebP сохранены в opencart/upload/energostor-theme/assets/img/editorial/,
имена совпадают со slug. Поля image и image_alt в articles.json передаются
в индекс, главную, /news и страницы статей. Обложки условные, а не изображения
конкретных моделей; внутри статей есть пояснение. Изображения включены в JSON-LD.

Все 25 просмотрены общим контактным листом. Проверены HTTPS и MIME WebP,
наличие изображений в HTML главной, ленты и статьи. Полная браузерная проверка
после публикации не выполнялась.
