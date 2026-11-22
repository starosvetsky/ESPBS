<?php
declare(strict_types=1);
// Read-only integration check; run outside webroot on Selectel.
require '/opt/energostor-next/upload/config.php';
require '/opt/energostor-next/ui-helpers.php';
mysqli_report(MYSQLI_REPORT_ERROR | MYSQLI_REPORT_STRICT);
$connection = new mysqli(DB_HOSTNAME,DB_USERNAME,DB_PASSWORD,DB_DATABASE,(int)DB_PORT);
$connection->set_charset('utf8mb4');
$db = new class($connection) {
    public function __construct(private mysqli $connection) {}
    public function query(string $sql): object {
        return (object)['rows'=>$this->connection->query($sql)->fetch_all(MYSQLI_ASSOC)];
    }
};
$brands = energostorUiBrands($db);
$groups = array_filter($brands, static fn(array $brand): bool => $brand['id']===$brand['canonical']);
$members = [];
foreach ($groups as $group) foreach ($group['members'] as $id) {
    if (isset($members[$id])) throw new RuntimeException('A manufacturer was counted twice');
    $members[$id] = true;
}
if (count($members)!==count($brands)) throw new RuntimeException('Manufacturer coverage was lost');
$counts = array_column($db->query('SELECT manufacturer_id, COUNT(*) AS total FROM '.DB_PREFIX.'product GROUP BY manufacturer_id')->rows,'total','manufacturer_id');
$routes = json_decode(file_get_contents('/opt/energostor-next/routes.json'),true,flags:JSON_THROW_ON_ERROR);
$paths = [];
foreach ($routes['routes'] as $path=>$route) if ($route['route']==='product/manufacturer.info') $paths[(int)$route['value']]=$path;
$checked = 0;
foreach ($groups as $group) {
    if (count($group['members'])<2) continue;
    $expected = array_sum(array_map(static fn(int $id):int => (int)($counts[$id]??0),$group['members']));
    $path = $paths[$group['id']];
    $html = shell_exec('curl --resolve energostor.ru:443:127.0.0.1 -sS '.escapeshellarg('https://energostor.ru'.$path));
    if (!is_string($html) || !preg_match('/<div class="ui-listing-toolbar"><p>\s*([\d\s]+)/u',$html,$match)) throw new RuntimeException('Missing live product counter: '.$path);
    $actual = (int)preg_replace('/\D/','',$match[1]);
    if ($actual!==$expected) throw new RuntimeException('Combined product count mismatch: '.$path.' expected '.$expected.' actual '.$actual);
    echo $group['name'].': '.$actual.' products from '.count($group['members'])." raw manufacturer records — OK\n";
    $checked++;
}
$total = (int)$db->query('SELECT COUNT(*) AS total FROM '.DB_PREFIX.'product')->rows[0]['total'];
echo 'PASS: '.count($groups).' display brands; '.(count($brands)-count($groups)).' aliases; '.$checked.' combined filters checked; '.$total." products retained\n";
