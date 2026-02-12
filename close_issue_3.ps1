# Фіксація кодування UTF-8 для gh CLI на Windows
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

# 0. Створення лейбла 'enhancement' (ігнорує помилку якщо вже існує)
Write-Host "Створення лейбла 'enhancement'..."
gh label create "enhancement" --repo borya-mbi/nkon-informer --description "New feature or request" --color "a2eeef" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "Лейбл вже існує або помилка - продовжуємо..."
}

# 1. Створення issue з лейблом 'enhancement'
$body = @"
## Опис

Метод _fetch_real_stock() потребує рефакторингу для коректної роботи з товарами, що мають обов'язкові випадаючі списки (наприклад, Eve MB31 з вибором шин/Busbars).

## Поточні проблеми
- Тихі збої: Товари з обов'язковими select елементами (шини) не отримують дані про залишок
- Немає обробки dropdown: При натисканні Add to Cart без вибору обов'язкової опції сайт повертає нерозпізнане повідомлення
- Голі except: Всі виключення перехоплюються без логування
- Один regex-патерн: Розпізнає лише only X left, пропускає інші формати NKON

## Бажана поведінка
1. Знаходити обов'язкові dropdown та обирати найкращу опцію (пріоритет - ІЗ шинами)
2. Логувати кожен шлях виходу з причиною
3. Підтримувати декілька форматів повідомлень про помилки (EN/UA)
4. Використовувати regex word boundary для фільтрації негативних ключових слів
"@

$title = "Рефакторинг _fetch_real_stock(): обробка dropdown, пріоритет шин, покращене логування"

Write-Host "Створення issue..."
$issueUrl = gh issue create --repo borya-mbi/nkon-informer --title $title --label "enhancement" --body $body

if ($LASTEXITCODE -ne 0) {
    Write-Error "Помилка при створенні issue"
    exit 1
}

Write-Host "Створено issue: $issueUrl"

# Витягуємо номер issue з URL
if ($issueUrl -match '/issues/(\d+)') {
    $issueNumber = $Matches[1]
    Write-Host "Номер issue: $issueNumber"
} else {
    Write-Host "Не вдалося визначити номер issue. Закрийте вручну."
    exit 1
}

# 2. Закриття issue з посиланням на коміт
$comment = @"
Реалізовано в коміті https://github.com/borya-mbi/nkon-informer/commit/d933208

Впроваджені зміни:
- Обробка dropdown: Визначає обов'язкові select елементи та обирає найкращу опцію перед перевіркою залишку
- Пріоритет шин: При виборі опцій надає перевагу варіантам ІЗ шинами (ключові слова: busbar/шини)
- Виправлення бага: Критична колізія підрядків - ні збігалося всередині шиНІ, відхиляючи ВСІ варіанти з шинами. Замінено на regex word boundary
- Діагностичне логування: Всі опції dropdown тепер відображаються в логах
- Логування тексту помилок: Нерозпізнані повідомлення логуються замість тихого ігнорування
- Декілька regex-патернів: Підтримка only X left, most you can purchase is X та українських варіантів
- Надійність: JS click fallback, коректна обробка виключень
"@

gh issue close $issueNumber --repo borya-mbi/nkon-informer --comment $comment

Write-Host "Issue #$issueNumber закрито."
