<?php
namespace Opencart\Catalog\Controller\Error;
class Gone extends \Opencart\System\Engine\Controller {
    public function index(): void {
        $this->document->setTitle('Страница больше не доступна — Энергостор');
        $this->response->addHeader('HTTP/1.1 410 Gone');
        $data['header'] = $this->load->controller('common/header');
        $data['footer'] = $this->load->controller('common/footer');
        $this->response->setOutput($this->load->view('error/gone',$data));
    }
}
