<?php
declare(strict_types=1);

function energostorUiSections(): array {
    $requestPath = rtrim(parse_url($_SERVER['REQUEST_URI'] ?? '/', PHP_URL_PATH) ?: '/', '/');
    $all = energostorRelease()['sections'];
    $groups = [];
    foreach ($all as $section) {
        if ($section['parent'] !== null) continue;
        $section['active'] = $section['url'] === $requestPath;
        $section['children'] = [];
        foreach ($all as $child) {
            if ($child['parent'] !== $section['slug']) continue;
            $child['active'] = $child['url'] === $requestPath;
            if ($child['active']) $section['active'] = true;
            $section['children'][] = $child;
        }
        $groups[] = $section;
    }
    return $groups;
}

function energostorUiSorts(array $sorts): array {
    $labels = ['p.sort_order-ASC'=>'По умолчанию', 'pd.name-ASC'=>'Название: А — Я',
        'pd.name-DESC'=>'Название: Я — А', 'p.model-ASC'=>'Артикул: А — Я', 'p.model-DESC'=>'Артикул: Я — А',
        'p.quantity-DESC'=>'По количеству'];
    foreach ($sorts as &$sort) $sort['text'] = $labels[$sort['value']] ?? $sort['text'];
    unset($sort);
    return $sorts;
}

// Read-side aliases only: retain every product, ID and original source record.
function energostorUiBrands(object $db): array {
    static $result;
    if ($result !== null) return $result;
    $rows = $db->query('SELECT manufacturer_id, name FROM ' . DB_PREFIX . 'manufacturer')->rows;
    $lookup = [];
    foreach ($rows as $row) $lookup[mb_strtolower(trim($row['name']), 'UTF-8')] = (int)$row['manufacturer_id'];
    $result = [];
    foreach ($rows as $row) {
        $id = (int)$row['manufacturer_id']; $name = trim($row['name']); $canonical = $id;
        if (preg_match('/^(.+?)\s+Диаметр,\s*мм\s*[—-]\s*\d+(?:[.,]\d+)?$/u', $name, $match)) {
            $canonical = $lookup[mb_strtolower(trim($match[1]), 'UTF-8')] ?? $id;
        } elseif (preg_match('/^Производитель:\s*(.+)$/u', $name, $match)) {
            $name = trim($match[1]); $canonical = $lookup[mb_strtolower($name, 'UTF-8')] ?? $id;
        }
        $result[$id] = ['id'=>$id, 'canonical'=>$canonical, 'name'=>$name, 'members'=>[]];
    }
    foreach ($result as $id => $brand) $result[$brand['canonical']]['members'][] = (int)$id;
    return $result;
}

function energostorUiManufacturerIds(int $id, object $db): array {
    $brands = energostorUiBrands($db);
    $canonical = $brands[$id]['canonical'] ?? $id;
    return $brands[$canonical]['members'] ?? [$id];
}

function energostorUiBrandName(int $id, object $db): string {
    $brands = energostorUiBrands($db);
    $canonical = $brands[$id]['canonical'] ?? $id;
    return $brands[$canonical]['name'] ?? '';
}

function energostorUiBrandGroups(array $categories, object $db): array {
    $brands = energostorUiBrands($db); $groups = [];
    foreach ($categories as $category) foreach ($category['manufacturer'] ?? [] as $brand) {
        $id = (int)$brand['manufacturer_id'];
        if (($brands[$id]['canonical'] ?? $id) !== $id) continue;
        $brand['name'] = energostorUiBrandName($id, $db);
        $letter = mb_strtoupper(mb_substr($brand['name'],0,1,'UTF-8'),'UTF-8');
        if (ctype_digit($letter)) $letter = '0–9';
        $groups[$letter]['name'] = $letter;
        $groups[$letter]['manufacturer'][] = $brand;
    }
    ksort($groups, SORT_NATURAL | SORT_FLAG_CASE);
    foreach ($groups as &$group) usort($group['manufacturer'], static fn($a,$b) => mb_strtolower($a['name'],'UTF-8') <=> mb_strtolower($b['name'],'UTF-8'));
    unset($group);
    return array_values($groups);
}

function energostorUiSearchSql(string $query, object $db): string {
    $words = array_slice(preg_split('/\s+/u', mb_substr(trim($query),0,160,'UTF-8'), -1, PREG_SPLIT_NO_EMPTY) ?: [],0,8);
    if (!$words) return '0=1';
    $haystack = "LOWER(REPLACE(CONCAT_WS(' ', `ui_m`.`name`, `p`.`model`, `pd`.`name`), '-', ''))";
    $conditions = [];
    foreach ($words as $word) {
        $word = str_replace('-', '', mb_strtolower($word,'UTF-8'));
        if ($word==='') continue;
        $word = str_replace(['\\','%','_'],['\\\\','\\%','\\_'],$word);
        $conditions[] = $haystack . " LIKE '" . $db->escape('%'.$word.'%') . "'";
    }
    if (!$conditions) return '0=1';
    return 'EXISTS (SELECT 1 FROM `' . DB_PREFIX . 'manufacturer` `ui_m` WHERE `ui_m`.`manufacturer_id` = `p`.`manufacturer_id` AND ' . implode(' AND ', $conditions) . ')';
}

function energostorUiRichtext(string $html): string {
    $data = energostorRelease();
    $html = str_replace([
        '<div>Бесплатная консультация от нашего технолога</div>',
        '<div>Сообщите ваши требования и мы предложим оптимальное решение, соответствующее потребностям и вашему бюджету</div>'
    ], '', $html);
    return preg_replace_callback('~href=([\x22\x27])([^\x22\x27]+)\1~u', static function(array $match) use($data): string {
        $href = html_entity_decode($match[2],ENT_QUOTES,'UTF-8');
        if (str_starts_with($href,'#') || $href==='./' || $href==='../') return $match[0];
        $parts = parse_url($href);
        if ($parts === false || (isset($parts['scheme']) && !in_array($parts['scheme'],['http','https'],true))) return $match[0];
        if (isset($parts['host']) && !in_array(strtolower($parts['host']),['energostor.ru','www.energostor.ru'],true)) return $match[0];
        $path = '/'.ltrim($parts['path'] ?? '', '/');
        $path = rtrim($path,'/') ?: '/';
        if ($path==='/' || $path==='/index.php' || isset($data['routes'][$path]) || preg_match('~\.[a-z0-9]{2,5}$~i',$path)) return $match[0];
        if (isset($data['aliases'][$path]) && $data['aliases'][$path] !== '') return $match[0];
        $lower = mb_strtolower($path,'UTF-8');
        if (isset($data['routes'][$lower])) {
            $target = $lower.(isset($parts['query'])?'?'.$parts['query']:'').(isset($parts['fragment'])?'#'.$parts['fragment']:'');
        } elseif (preg_match('~^/[a-zA-Z0-9-]{2,40}$~',$path)) {
            $target = '/vendors?brand='.rawurlencode(ltrim($path,'/'));
        } else {
            $target = '/catalog';
        }
        return 'href='.$match[1].htmlspecialchars($target,ENT_QUOTES,'UTF-8').$match[1];
    }, $html) ?? $html;
}
