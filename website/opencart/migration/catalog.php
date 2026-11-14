<?php
namespace Opencart\Catalog\Controller\Information;

class Catalog extends \Opencart\System\Engine\Controller {
    public function index(): void {
        $this->document->setTitle('Каталог оборудования — Энергостор');
        $this->document->setDescription('Электротехническое, промышленное и сетевое оборудование. Выберите раздел или найдите позицию по артикулу.');
        $data['sections'] = array_filter(energostorRelease()['sections'], static fn(array $section): bool => $section['parent'] === null);
        $data['header'] = $this->load->controller('common/header');
        $data['footer'] = $this->load->controller('common/footer');
        $this->response->setOutput($this->load->view('information/catalog', $data));
    }

    public function vendors(): void {
        $this->document->setTitle('Вендоры — Энергостор');
        $this->document->setDescription('Производители оборудования и комплектующих, с которыми работает Энергостор.');
        $data['header'] = $this->load->controller('common/header');
        $data['footer'] = $this->load->controller('common/footer');
        $this->response->setOutput($this->load->view('information/vendors', $data));
    }
}
