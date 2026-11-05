<?php
/**
 * Обработчик формы заявки для статической главной страницы.
 * Кладётся рядом с index.html; требует PHP 7.4+ и работающего mail() (sendmail).
 *
 * Настройки ниже — единственное, что нужно менять при переезде.
 */

declare(strict_types=1);

const MAIL_TO      = 'info@energostor.ru';
const MAIL_FROM    = 'no-reply@energostor.ru'; // должен быть на домене сайта
const MAIL_SUBJECT = 'Заявка с сайта energostor.ru';
const SITE_URL     = 'https://energostor.ru';

header('Content-Type: application/json; charset=utf-8');

function respond(int $code, array $payload): void
{
    http_response_code($code);
    echo json_encode($payload, JSON_UNESCAPED_UNICODE);
    exit;
}

if (($_SERVER['REQUEST_METHOD'] ?? '') !== 'POST') {
    respond(405, ['ok' => false, 'error' => 'Method not allowed']);
}

$raw = static function (string $key): string {
    $value = $_POST[$key] ?? '';
    if (!is_string($value)) {
        return '';
    }
    $value = trim(str_replace(["\r", "\n", "%0a", "%0d"], ' ', $value));
    return mb_substr($value, 0, 2000);
};

$name     = $raw('name');
$phone    = $raw('phone');
$email    = $raw('email');
$company  = $raw('company');
$message  = $raw('message');
$subject  = $raw('subject') ?: MAIL_SUBJECT;
$consent  = isset($_POST['consent']) && is_string($_POST['consent']) && $_POST['consent'] === 'on';

if ($phone === '') {
    respond(422, ['ok' => false, 'error' => 'Не указан телефон']);
}

$digits = preg_replace('/\D/', '', $phone);
if (!preg_match('/^[0-9+()\-\s]{7,25}$/', $phone) || !preg_match('/^7[0-9]{10}$/', $digits)) {
    respond(422, ['ok' => false, 'error' => 'Некорректный телефон']);
}

if ($email !== '' && !filter_var($email, FILTER_VALIDATE_EMAIL)) {
    respond(422, ['ok' => false, 'error' => 'Некорректный e-mail']);
}

if (!$consent) {
    respond(422, ['ok' => false, 'error' => 'Нет согласия на обработку данных']);
}

$lines = [
    'Новая заявка с главной страницы',
    '',
    'Тема:      ' . $subject,
    'Имя:       ' . ($name !== '' ? $name : '—'),
    'Телефон:   ' . $phone,
    'E-mail:    ' . ($email !== '' ? $email : '—'),
    'Компания:  ' . ($company !== '' ? $company : '—'),
    'Сообщение: ' . ($message !== '' ? $message : '—'),
    '',
    'Страница:  ' . SITE_URL,
    'Дата:      ' . date('d.m.Y H:i'),
    'IP:        ' . ($_SERVER['REMOTE_ADDR'] ?? '—'),
];

$headers = [
    'From: Энергостор <' . MAIL_FROM . '>',
    'Reply-To: ' . ($email !== '' ? $email : MAIL_FROM),
    'Content-Type: text/plain; charset=UTF-8',
    'X-Mailer: energostor-static',
];

$sent = mail(
    MAIL_TO,
    '=?UTF-8?B?' . base64_encode($subject) . '?=',
    implode("\n", $lines),
    implode("\r\n", $headers)
);

if (!$sent) {
    respond(500, ['ok' => false, 'error' => 'Не удалось отправить письмо']);
}

respond(200, ['ok' => true]);
