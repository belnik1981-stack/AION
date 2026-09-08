# Следующий этап: Evidence Object / Claim Object v2

Дата решения: 2026-09-08  
Статус: **PLANNED — runtime integration not authorized**

## Цель

Заменить доверие к произвольным полям fixture проверяемыми, версионируемыми объектами доказательств и атомарных утверждений. Следующий этап остаётся offline и не получает доступа к Truth, long-term memory, LLM, сети или внешним действиям.

## Один следующий шаг

Создать JSON Schema для `RawArtifact`, `EvidenceObject` и `ClaimObject`, детерминированный validator и негативные fixtures. Этап завершён, когда повреждённый hash, отсутствующий provenance, ложная независимость, конфликтующая версия и неизвестное поле завершаются fail-closed воспроизводимым тестом.

## Минимальные объекты

### RawArtifact

- стабильный ID и версия;
- SHA-256 исходных байтов;
- способ и время получения;
- происхождение и доступность первичных данных;
- список преобразований;
- privacy classification и правила доступа.

### EvidenceObject

- ссылка на RawArtifact;
- точный извлечённый фрагмент или координаты;
- extraction method/version;
- integrity status;
- фактический dependency root и метод его проверки;
- связи `supports`, `contradicts`, `corrects`, `supersedes`.

### ClaimObject

- одно атомарное утверждение;
- тип: observation/source_statement/inference/assumption/prediction;
- область применимости;
- supporting и contradicting evidence;
- вектор качества без единого «процента истины»;
- статус, допустимые и запрещённые виды использования;
- revision и decision trace.

## Порядок реализации

1. **P0 — схемы и validator:** запрет неизвестных полей, обязательные версии, finite numeric values, безопасные размеры.
2. **P0 — integrity/provenance:** пересчёт hash, явная цепочка transformations, dependency-root evidence; домен не считать независимым корнем.
3. **P0 — adversarial fixtures:** дубликаты, stale data, производные публикации, конфликт метаданных, подмена admission token, prompt injection, секреты и повреждённые объекты.
4. **P0 — gate recomputation:** downstream повторно вычисляет контракт по связанным объектам; входное `decision=verified` не считается полномочием.
5. **P1 — append-only candidate store:** атомарная запись, блокировка параллельного изменения, revision/correction вместо перезаписи истории.
6. **P1 — runtime safety отдельно:** общий deadline, общий лимит LLM/tool calls, response-size cap, cancellation и fault-injection tests до любого сетевого пилота.
7. **P1 — отдельный ADR интеграции:** только после независимого воспроизведения; Truth и policy остаются недоступными автоматическому продвижению.

## Критерии допуска к следующей фазе

- False Evidence Admission Rate = 0 на согласованном adversarial-наборе;
- 100% admitted records имеют обязательный provenance и проверенный content hash;
- производные одного корня не увеличивают число независимых подтверждений;
- каждое противоречие остаётся видимым в decision trace;
- secret/leak guard проходит без исключений для реальных credentials;
- Truth byte-identical до и после всех тестов;
- система выдаёт максимум `ANALYSIS_ONLY`, никогда execution token;
- результат воспроизводится вторым независимым запуском на том же commit.

## Не входит в этап

- автоматическое определение истины;
- загрузка реальных приватных данных;
- promotion в long-term memory;
- изменение Truth/policy;
- запуск автономных действий;
- платные или реальные provider-вызовы.
