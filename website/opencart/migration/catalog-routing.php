<?php
declare(strict_types=1);

// Loaded only by the storefront front controller.
function energostorRelease(): array {
    static $release;
    return $release ??= json_decode(
        file_get_contents(dirname(DIR_OPENCART) . '/routes.json'), true, flags: JSON_THROW_ON_ERROR
    );
}

function energostorRelative(string $path): string {
    return ltrim($path, '/');
}

function energostorTarget(string $route, array $query): ?string {
    if ($route === 'common/home') {
        return '/';
    }
    static $index;
    if ($index === null) {
        $index = [];
        foreach (energostorRelease()['routes'] as $path => $entry) {
            $index[$entry['route']][$entry['value']] = $path;
        }
    }
    $key = match ($route) {
        'product/product' => 'product_id',
        'product/category' => 'path',
        'product/manufacturer.info' => 'manufacturer_id',
        'information/information' => 'information_id',
        default => '',
    };
    return $index[$route][$key === '' ? '' : (string)($query[$key] ?? '')] ?? null;
}

function energostorRequest(): void {
    $path = rawurldecode(parse_url($_SERVER['REQUEST_URI'] ?? '/', PHP_URL_PATH) ?: '/');
    if (!empty($_SERVER['ENERGOSTOR_PREVIEW']) && str_starts_with($path, '/energostor-next/')) {
        $path = substr($path, strlen('/energostor-next'));
    }
    $path = rtrim($path, '/') ?: '/';
    $data = energostorRelease();
    $get = $_SERVER['REQUEST_METHOD'] === 'GET' || $_SERVER['REQUEST_METHOD'] === 'HEAD';
    if ($get && isset($data['aliases'][$path])) {
        $target = $data['aliases'][$path];
        if ($target !== '') {
            header('Location: ' . HTTP_SERVER . energostorRelative($target), true, 301);
            exit;
        }
        http_response_code(410);
        header('Content-Type: text/plain; charset=UTF-8');
        echo 'Страница удалена.';
        exit;
    }
    if ($get && isset($data['routes'][$path])) {
        $route = $data['routes'][$path];
        foreach (['product_id','manufacturer_id','information_id','path','store_id','language','currency','_route_'] as $key) {
            unset($_GET[$key]);
        }
        if ($route['key'] !== '') {
            $_GET[$route['key']] = $route['value'];
        }
        $_GET['route'] = $route['route'];
        if (($_GET['sort'] ?? '') === 'p.price') {
            unset($_GET['sort'], $_GET['order']);
        }
        return;
    }
    if ($path !== '/' && $path !== '/index.php') {
        $_GET['route'] = 'error/not_found';
        return;
    }
    $route = $_GET['route'] ?? 'common/home';
    if (!is_string($route) || !$get) {
        $_GET['route'] = 'error/not_found';
        return;
    }
    if ($route === 'product/search') {
        header('X-Robots-Tag: noindex, follow');
        unset($_GET['store_id'], $_GET['language'], $_GET['currency']);
        return;
    }
    $target = energostorTarget($route, $_GET);
    if ($target !== null && ($path === '/index.php' || $route !== 'common/home')) {
        $params = array_intersect_key($_GET, array_flip(['page','sort','order','limit','filter']));
        $suffix = $params ? '?' . http_build_query($params) : '';
        header('Location: ' . HTTP_SERVER . energostorRelative($target) . $suffix, true, 301);
        exit;
    }
    $_GET['route'] = $route === 'common/home' ? $route : 'error/not_found';
}

final class EnergostorLinks {
    public function rewrite(string $link): string {
        parse_str(parse_url($link, PHP_URL_QUERY) ?? '', $query);
        $route = $query['route'] ?? '';
        $path = energostorTarget($route, $query);
        if ($path === null) {
            return $link;
        }
        $params = array_intersect_key($query, array_flip(['page','sort','order','limit','filter']));
        return HTTP_SERVER . energostorRelative($path) . ($params ? '?' . http_build_query($params) : '');
    }
}

function energostorSeo(array $query): array {
    $route = $query['route'] ?? 'common/home';
    $path = energostorTarget($route, $query);
    $entry = $path === null ? [] : (energostorRelease()['routes'][$path] ?? []);
    $page = max(1, (int)($query['page'] ?? 1));
    $pagination = in_array($route, ['product/category','product/manufacturer.info'], true) && $page > 1;
    return [
        'canonical' => $path === null ? '' : 'https://energostor.ru' . $path . ($pagination ? '?page='.$page : ''),
        'noindex' => $path === null || !empty($entry['noindex']) || isset($query['filter']) || isset($query['sort']) || isset($query['limit']),
    ];
}
