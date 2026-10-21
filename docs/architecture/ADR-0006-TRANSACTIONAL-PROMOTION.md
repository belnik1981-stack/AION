# ADR-0006: транзакционный promotion в long-term memory

Статус: принято и проверено offline
Дата: 2026-10-20

## Контекст

`promote_verified_claim` сначала добавлял claim в long-term knowledge и затем
дописывал audit JSONL. Отказ второй операции оставлял видимое «подтверждённое»
знание без доказательной записи. Прямой `add_long_term_lesson` также обходил
verification gate.

## Решение

Promotion выполняется как идемпотентная восстанавливаемая последовательность:

1. повторно вычислить integrity hash, claim id и все поля verification decision;
2. отклонить policy слабее минимального `VerificationPolicy()`;
3. создать crash-safe transaction journal со статусом `prepared`;
4. записать уникальное audit-событие `promotion_prepared`;
5. поместить claim в `pending_promotions`, невидимое для long-term чтения;
6. записать уникальное audit-событие `promote_to_long_term`;
7. только после успешного committed audit перенести claim в
   `learned_lessons`;
8. отметить transaction как `committed`.

Каждый audit event имеет детерминированный `event_id`. Повтор или восстановление
не создаёт дубликат. Transaction содержит digest committed audit record;
несовпадение блокирует продолжение.

Прямая запись через `add_long_term_lesson` запрещена. Claim, evidence или reviewer
с обнаруженным секретом блокируют всю операцию. `Truth` не изменяется.

Один `source_id` считается одним источником независимо от числа повторов;
противоречивые dependency groups одного source не увеличивают независимость.
Нефинитные числа, пустой `source_type` и превышение границ claim/evidence
блокируются до promotion.

## Восстановление

`recover_pending_promotions()` продолжает незавершённые операции с последнего
зафиксированного состояния. Все этапы идемпотентны. Если audit log содержит
частично записанную или некорректную JSONL-строку, новый append блокируется без
изменения существующего файла.

## Проверка

`tests/harness/test_verification_integrity.py` проверяет:

- повторную оценку и защиту integrity hash;
- полное совпадение derived evaluation и claim id;
- неослабляемый policy floor, дедупликацию source id и числовые/размерные
  границы;
- обязательного reviewer;
- полный успешный promotion;
- два audit events и committed journal;
- идемпотентный повтор;
- искусственный отказ committed audit;
- невидимость pending claim;
- успешное продолжение через recovery.

## Границы решения

- транзакция локальная и не заменяет распределённый consensus;
- reviewer и заявленные свойства evidence не доказывают внешнюю подлинность;
- повреждённый audit log сохраняется и требует отдельной диагностической
  процедуры, а не автоматического удаления строки.
