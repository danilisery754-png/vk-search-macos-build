# VK LIVE registry

Моки и unit-тесты не считаются доказательством работы живого VK. Перед релизом каждая строка переводится из `NOT_TESTED` только после проверки на реальном тестовом аккаунте.

| Механизм | Метод/путь | Контракт | LIVE | Что зафиксировать |
|---|---|---:|---:|---|
| Проверка токена | `users.get` | OK | NOT_TESTED | VK ID, дата, версия API |
| Получение токена | Edge/Chromium → VKHost OAuth | Код перенесён | NOT_TESTED | экраны, 2FA, captcha, URL без токена |
| ЛС сообществу | `messages.send`, `peer_id=-group_id`, `random_id` | OK | NOT_TESTED | рабочая группа, message_id |
| ЛС закрыты | `messages.send` error | Классификатор есть | NOT_TESTED | точный code/message |
| Чёрный список/ограничение | `messages.send` error | Консервативно | NOT_TESTED | точный code/message |
| Предложенная запись | `wall.post`, `owner_id=-group_id` | OK | NOT_TESTED | post_id и появление в предложке |
| Предложка закрыта | `wall.post` error | Консервативно | NOT_TESTED | точный code/message |
| Диалоги | `messages.getConversations` | OK | NOT_TESTED | список/extended/unread |
| История | `messages.getHistory` | OK | NOT_TESTED | входящие/исходящие |
| Прочтение | `messages.markAsRead`, `in_read`/`out_read` | OK | NOT_TESTED | unread исчез, маркеры совпали |
| Ответ | `messages.send` для peer диалога | OK | NOT_TESTED | правильный аккаунт |
| Открытие сообщений | сохранённый Edge/Chromium profile → `/im` | Код есть | NOT_TESTED | окно открылось без повторного входа |
| Тихое обновление токена | сохранённый profile | Код есть | NOT_TESTED | identity совпадает |

Источники контрактов:

- https://github.com/VKCOM/vk-api-schema/blob/master/messages/methods.json
- https://github.com/VKCOM/vk-api-schema/blob/master/wall/methods.json

Правило: при отличии живого поведения сначала обновить registry и тест-контракт, затем менять VK adapter. Соседние процессы не трогать.
