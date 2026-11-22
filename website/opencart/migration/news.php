<?php
namespace Opencart\Catalog\Controller\Information;

class News extends \Opencart\System\Engine\Controller {
    public function index(): void {
        $items = json_decode(file_get_contents(dirname(DIR_OPENCART) . '/editorial-index.json'), true, flags: JSON_THROW_ON_ERROR);
        $total = count($items);
        $last = max(1, (int)ceil($total / 20));
        $page = max(1, min($last, (int)($this->request->get['page'] ?? 1)));
        $this->document->setTitle('Новости и практика — Энергостор' . ($page > 1 ? ' — страница '.$page : ''));
        $this->document->setDescription('Новинки электротехники и автоматизации, обновления оборудования и практические материалы для проектирования и закупок. Ссылки на первоисточники в каждом материале.');
        $this->document->addStyle(HTTP_SERVER . 'energostor-theme/assets/css/editorial.css?v=1');
        $data['articles'] = array_slice($items, ($page - 1) * 20, 20);
        $data['total'] = $total;
        $data['page'] = $page;
        $data['last'] = $last;
        $data['previous'] = $page > 1 ? HTTP_SERVER . 'news' . ($page > 2 ? '?page='.($page - 1) : '') : '';
        $data['next'] = $page < $last ? HTTP_SERVER . 'news?page='.($page + 1) : '';
        $data['header'] = $this->load->controller('common/header');
        $data['footer'] = $this->load->controller('common/footer');
        $this->response->setOutput($this->load->view('information/news', $data));
    }
}
