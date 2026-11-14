<?php
// Convert the captured Tilda pages into content for OpenCart Information.
declare(strict_types=1);

$folder = $argv[1];
$entries = json_decode(file_get_contents($folder . '/index.json'), true, flags: JSON_THROW_ON_ERROR);
$output = [];
$duplicates = [
    '/2' => '/about', '/13' => '/partneram', '/fpartners' => '/partneram',
    '/12341rw' => '/politika', '/me' => '/electrooborudovanie',
    '/si' => '/intergration', '/to' => '/tvstuff',
    '/promtext' => '/tpost/2026',
    '/ibprinokru' => '/tpost/po2bpcg7i1-o-rinke-rossiiskih-ibp',
    '/smthaboutg' => '/tpost/egx473sup1-koe-chto-interesnoe-o-gidravlicheskom-ob',
];
$retired = ['/1414', '/777', '/nf', '/pp', '/q3412341234', '/page126582966.html'];
$allowed = ['a', 'b', 'strong', 'i', 'em', 'u', 'br', 'p', 'div', 'span', 'section', 'figure', 'figcaption',
    'ul', 'ol', 'li', 'h2', 'h3', 'h4', 'table', 'thead', 'tbody', 'tr', 'th', 'td', 'img'];
$currency = '/(?:\d[\d\h.,]*\h*(?:₽|руб(?:\.|лей|ля)?\b|RUB\b|USD\b|EUR\b|\$|€)|[\$€₽]\h*\d[\d\h.,]*)/iu';

function scrub(DOMNode $node, array $allowed, string $currency): void {
    foreach (iterator_to_array($node->childNodes) as $child) {
        if ($child instanceof DOMText) {
            $child->nodeValue = preg_replace($currency, '', $child->nodeValue);
            continue;
        }
        if (!$child instanceof DOMElement || !in_array($child->tagName, $allowed, true)) {
            $node->removeChild($child);
            continue;
        }
        foreach (iterator_to_array($child->attributes) as $attr) {
            if (!in_array($attr->name, ['href', 'src', 'alt', 'data-original', 'data-img-zoom-url'], true)) {
                $child->removeAttributeNode($attr);
            }
        }
        if ($child->tagName === 'a') {
            $href = $child->getAttribute('href');
            if (!preg_match('~^(?:https?://|/[^/]|mailto:|tel:)~i', $href)) {
                $child->removeAttribute('href');
            } else {
                $path = preg_replace('~^https?://(?:www\.)?energostor\.ru(?=/|$)~i', '', $href);
                $child->setAttribute('href', $path ?: '/');
            }
        }
        if ($child->tagName === 'img') {
            $src = $child->getAttribute('data-original') ?: $child->getAttribute('src');
            if (!preg_match('~^https://~i', $src)) {
                $node->removeChild($child);
                continue;
            }
            $child->setAttribute('src', $src);
            $child->removeAttribute('data-original');
            $child->removeAttribute('data-img-zoom-url');
            $child->setAttribute('loading', 'lazy');
        }
        scrub($child, $allowed, $currency);
    }
}

foreach ($entries as $entry) {
    $path = parse_url($entry['url'], PHP_URL_PATH);
    if ($path === '/' || $path === '/sitemap') {
        continue;
    }
    if (isset($duplicates[$path])) {
        $output[$path] = ['redirect' => $duplicates[$path]];
        continue;
    }
    if (in_array($path, $retired, true)) {
        $output[$path] = ['retired' => true];
        continue;
    }
    $raw = file_get_contents($folder . '/' . $entry['file']);
    $doc = new DOMDocument();
    @$doc->loadHTML('<?xml encoding="UTF-8">' . $raw, LIBXML_NONET);
    $xpath = new DOMXPath($doc);
    $title = trim($xpath->evaluate('string(//title)'));
    $meta = trim($xpath->evaluate('string(//meta[@name="description"]/@content)'));
    if (str_contains($path, '/tproduct/') && preg_match('/\bproduct = (\{.*?\});/s', $raw, $match)) {
        $product = json_decode($match[1], true, flags: JSON_THROW_ON_ERROR);
        $output[$path] = [
            'title' => $title, 'description' => $meta,
            'product' => true,
            'images' => array_column($product['gallery'] ?? [], 'img'),
        ];
        continue;
    }
    $nodes = $xpath->query('//*[@id="allrecords"]//*[contains(concat(" ",normalize-space(@class)," ")," tn-atom ") or contains(concat(" ",normalize-space(@class)," ")," t-text ") or contains(concat(" ",normalize-space(@class)," ")," t-descr ") or contains(concat(" ",normalize-space(@class)," ")," t-title ") or contains(concat(" ",normalize-space(@class)," ")," t-card__title ") or self::img or self::table]');
    if (str_starts_with($path, '/tpost/')) {
        $article = $xpath->query('//*[@itemprop="articleBody"]');
        if ($article->length) {
            $nodes = $article;
        }
    }
    $seen = [];
    $body = [];
    foreach ($nodes as $node) {
        if ($xpath->evaluate('boolean(ancestor::header|ancestor::footer|ancestor::form|ancestor::*[@data-record-type="758"]|ancestor::*[@data-record-type="121"])', $node)) {
            continue;
        }
        $clone = $node->cloneNode(true);
        if (in_array($node->tagName, ['img','a'], true)) {
            $box = $doc->createElement('div');
            $box->appendChild($clone);
            $clone = $box;
        }
        scrub($clone, $allowed, $currency);
        $plain = trim(preg_replace('/\s+/u', ' ', $clone->textContent));
        $hasImage = $clone->getElementsByTagName('img')->length > 0;
        if (($plain === '' || $plain === $title) && !$hasImage) {
            continue;
        }
        $html = '';
        foreach ($clone->childNodes as $child) {
            $html .= $doc->saveHTML($child);
        }
        if ($node->tagName === 'table') {
            $html = '<table>' . $html . '</table>';
        }
        $key = $plain !== '' ? $plain : $html;
        if (!isset($seen[$key])) {
            $seen[$key] = true;
            $body[] = '<div>' . $html . '</div>';
        }
    }
    $output[$path] = ['title' => $title, 'description' => preg_replace($currency, '', $meta), 'html' => implode("\n", $body)];
}
echo json_encode($output, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES | JSON_THROW_ON_ERROR);
