<?php
namespace Opencart\Catalog\Controller\Information;

class Lead extends \Opencart\System\Engine\Controller {
    public function index(): void {
        $this->response->addHeader('Content-Type: application/json; charset=utf-8');
        $this->response->addHeader('Cache-Control: no-store');
        if (($this->request->server['REQUEST_METHOD'] ?? '') !== 'POST') {
            $this->reply(405, 'Используйте форму на сайте.'); return;
        }
        $origin = $this->request->server['HTTP_ORIGIN'] ?? '';
        if (!in_array($origin, ['https://energostor.ru', 'https://www.energostor.ru'], true)) {
            $this->reply(403, 'Обновите страницу и повторите отправку.'); return;
        }
        $post = $this->request->post;
        $values = [];
        foreach (['name'=>120,'phone'=>40,'email'=>254,'company'=>200,'message'=>5000,'subject'=>160] as $key=>$max) {
            if (isset($post[$key]) && !is_string($post[$key])) { $this->reply(422,'Проверьте поля формы.'); return; }
            $values[$key] = trim((string)($post[$key] ?? ''));
            if (mb_strlen($values[$key]) > $max || str_contains($values[$key], "\0")) { $this->reply(422,'Слишком длинное значение поля.'); return; }
        }
        if (!is_string($post['consent'] ?? null) || empty($post['consent']) || strlen(preg_replace('/\D/', '', $values['phone'])) < 7 || ($values['email'] !== '' && !filter_var($values['email'], FILTER_VALIDATE_EMAIL))) {
            $this->reply(422, 'Укажите телефон, проверьте email и подтвердите согласие.'); return;
        }
        if (!empty($post['website'])) { $this->reply(422,'Не удалось проверить форму.'); return; }
        if ($this->config->get('config_mail_engine') !== 'smtp' || !$this->config->get('config_mail_smtp_hostname') || !$this->config->get('config_mail_smtp_username') || !$this->config->get('config_mail_smtp_password')) {
            $this->reply(503, 'Отправка временно недоступна. Напишите на info@energostor.ru.'); return;
        }
        // Fixed number of counter files, no contact data stored in the limiter.
        $ip = $this->request->server['REMOTE_ADDR'] ?? 'unknown';
        $bucket = substr(hash('sha256', $ip),0,3);
        $file = fopen(DIR_CACHE.'lead-rate-'.$bucket, 'c+');
        if (!$file || !flock($file, LOCK_EX)) { $this->reply(503,'Попробуйте позднее.'); return; }
        $state = json_decode(stream_get_contents($file), true) ?: [];
        $now = time();
        if ($now - ($state['start'] ?? 0) > 900) $state = ['start'=>$now,'count'=>0];
        if (($state['count'] ?? 0) >= 5) { fclose($file); $this->reply(429,'Слишком много отправок. Повторите через 15 минут.'); return; }
        $state['count']++;
        rewind($file); ftruncate($file,0); fwrite($file,json_encode($state)); fflush($file); flock($file, LOCK_UN); fclose($file);
        try {
            $mail = new \Opencart\System\Library\Mail('smtp', [
                'smtp_hostname'=>$this->config->get('config_mail_smtp_hostname'),
                'smtp_username'=>$this->config->get('config_mail_smtp_username'),
                'smtp_password'=>html_entity_decode($this->config->get('config_mail_smtp_password'), ENT_QUOTES,'UTF-8'),
                'smtp_port'=>$this->config->get('config_mail_smtp_port'),
                'smtp_timeout'=>15
            ]);
            $mail->setTo('info@energostor.ru');
            $mail->setFrom($this->config->get('config_email'));
            $mail->setSender('Энергостор — сайт');
            if ($values['email'] !== '') $mail->setReplyTo($values['email']);
            $mail->setSubject('Заявка с energostor.ru');
            $body = 'Получено: '.gmdate('c')."\n\n";
            foreach (['subject'=>'Форма','name'=>'Имя','phone'=>'Телефон','email'=>'Email','company'=>'Компания','message'=>'Задача'] as $key=>$label) $body .= $label.': '.$values[$key]."\n\n";
            $body .= 'Пользователь подтвердил согласие на обработку данных для ответа на обращение.';
            $mail->setText($body);
            $mail->send();
            $this->response->setOutput(json_encode(['ok'=>true]));
        } catch (\Throwable $error) {
            // Never log credentials, contact fields or SMTP exception messages.
            $this->log->write('Website lead SMTP delivery failed.');
            $this->reply(503,'Не удалось отправить заявку. Напишите на info@energostor.ru.');
        }
    }
    private function reply(int $status,string $message): void {
        $this->response->addHeader('HTTP/1.1 '.$status);
        $this->response->setOutput(json_encode(['ok'=>false,'message'=>$message],JSON_UNESCAPED_UNICODE));
    }
}
