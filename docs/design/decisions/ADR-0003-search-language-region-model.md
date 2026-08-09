# ADR-0003 — Search language и region: common tags + configured region registry

**Статус:** accepted

## 1. Контекст

SearXNG и Yandex Search имеют разные localization models.

- Language может быть выражен строковым языковым кодом/tag.
- Yandex имеет собственные region identifiers.
- SearXNG common API не предоставляет эквивалентную универсальную city-region модель для всех engines.

Web Access не должен:

- копировать Yandex `lr` integer в общий Search contract;
- запускать geocoding внутри Search;
- угадывать регион по произвольной строке;
- превращать provider-specific справочник в обязательную schema всех providers.

---

## 2. Решение — language

Common `language` представлен нормализованным language tag string.

Baseline semantics:

```text
null
→ provider/configured default

"ru"
"en"
"ru-RU"
"en-GB"
→ explicit language preference/tag
```

Application выполняет syntactic normalization/validation, но provider adapter определяет, поддерживает ли конкретный tag.

Точное подмножество BCP 47, реально поддерживаемое v0.2 schemas, фиксируется implementation и tests.

Если provider способен только на base language, adapter может безопасно свести `ru-RU` → `ru` только если это явно документировано как lossless-enough provider mapping и возвращает resolved language metadata. Иначе option rejected.

---

## 3. Решение — region

Common `region` — **canonical configured `SearchRegionId`**, а не provider raw value.

Примеры naming convention:

```text
ru
ru-moscow
ru-moscow-oblast
us
us-california
```

Это service-controlled identifiers; конкретный registry не является global ontology мира.

---

## 4. SearchRegionRegistry

Configuration содержит entries:

```text
region_id
human label
provider mappings
```

Концептуально:

```json
{
  "region_id": "ru-moscow",
  "label": "Москва",
  "providers": {
    "yandex": {
      "region_id": "<provider-specific value>"
    }
  }
}
```

Provider-specific value остаётся infrastructure config и не попадает в common Search request.

---

## 5. Provider mapping

Если query содержит `region="ru-moscow"`:

1. SearchRegionRegistry находит exact canonical entry.
2. Проверяется mapping для выбранного provider.
3. Если mapping существует → adapter использует его.
4. Если mapping отсутствует → query rejected `unsupported_region`.

Никакого fuzzy matching/geocoding/provider guessing.

---

## 6. `region = null`

Означает:

```text
не задавать explicit common region;
использовать configured/provider default semantics.
```

Web Access не выводит region автоматически из IP/Principal/языка, если отдельная policy не будет спроектирована позднее.

---

## 7. SearXNG

Если configured SearXNG profile не имеет доказуемой mapping semantics для common region:

```text
region != null
→ rejected unsupported_option/unsupported_region
```

Web Access не симулирует region через hidden query rewriting.

Language остаётся отдельной поддерживаемой capability.

---

## 8. Yandex

Yandex adapter маппит canonical SearchRegionId в собственный provider region identifier.

Application/MCP/REST не знают raw Yandex region ID.

Обновление Yandex region mapping является configuration change и должно иметь observable revision.

---

## 9. REST

REST может предоставлять provider capability/region discovery через:

```text
GET /api/v1/search/providers
```

Response может включать supported canonical region IDs/labels для authorized/programmatic clients.

Это позволяет UI программно построить selection.

---

## 10. MCP

`web_search.region` остаётся optional string canonical ID.

Description объясняет:

- поле не является свободным названием места;
- используется только для явно настроенных регионов;
- если регион не нужен, поле лучше опустить;
- unsupported ID вернёт repairable error.

MCP не получает отдельный region-list tool в core catalog только ради этого option.

Собственный агент обычно может оставить `region` unset и использовать provider default.

---

## 11. Почему не ISO-only

ISO 3166 хорошо описывает страны/часть административных единиц, но provider search regions могут иметь другую granularity и provider-specific справочник.

Строгое ISO-only поле либо потеряет полезную Yandex city-region capability, либо потребует сложной provider-independent geospatial ontology.

Canonical service registry проще и честнее.

---

## 12. Почему не free-form location

Free-form:

```text
region="Москва"
```

потребовал бы:

- geocoding;
- ambiguity handling;
- locale normalization;
- provider mapping;

что не является ответственностью Search.

Поэтому только exact configured ID.

---

## 13. Configuration validation

Startup/config revision должен rejected:

- duplicate region_id;
- malformed canonical ID;
- duplicate/conflicting provider mapping;
- provider mapping для неизвестного provider;
- invalid provider-specific value, если adapter может проверить его статически.

---

## 14. Cache semantics

Cache key использует canonical region ID + region registry/config revision.

Изменение provider mapping не должно продолжать выдавать cache, созданный под старой mapping semantics.

---

## 15. Acceptance

1. Common contract не содержит Yandex `lr`/raw region integer.
2. Search не вызывает geocoder.
3. Exact canonical region mapping deterministic.
4. Missing provider mapping rejected, не ignored.
5. `null` не выводит регион скрыто.
6. Region mapping revision входит cache/config provenance.
7. REST способен показать supported canonical regions.
8. MCP использует optional canonical string, без tool explosion.
9. Language и region остаются независимыми fields.

---

## 16. Не определяется

- полный initial region registry;
- exact BCP 47 validation library;
- конкретные Yandex region IDs;
- UI labels/localization registry;
- future geolocation-aware default policy.

Эти значения/configuration добавляются v0.2 implementation без изменения common model.
