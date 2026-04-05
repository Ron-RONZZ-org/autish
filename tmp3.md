## `encik`

1. add more detailed HELP for recently implemented JSON support:

  - reminder for format: 
```
  datumo.{var-name}="""
  {
    "metriko": {
      "en": "Unemployment rate",
      "fr": "Taux de chômage"
    }
  },
  "meta": {
    "landoj": "France",
    },
  "datumo": [
    {"jaro", "valoro"},
    {2010, 9.3},
    {2011, 9.2}
  ]
  "etikedo": {
  "jaro": {
  "en": "year",
  "eo": "jaro",
  "fr": "année"
  },
  "valoro": {
  "en": "value",
  "eo": "valoro",
  "fr": "valeur"
  }
  }
}"""
```
{var-name} is an arbitrary name that user assigns to a dataset and must be unique.
And the json string includes:
  - (optional) `metriko` STRING/DICTIONARY: title/label of data
  - (optional) "meta" DICTIONARY: provides additional information identifying the data set. Note that each metadata can have single value but also multi-lingual values: 
 
e.g.,
```
  "meta": {
    "country": {
      "en": "China",
      "fr": "Chine",
      "eo": "Ĉino"
      }
      },
```
  - (required) `datumo` LIST : actual data. first element of list optionally specify labels for each column
  - (optional) `etikedo` DICTIONARY: Specifies the column labels in different languages.

2. add optional `lingvo="{comma separated 2-letter-code(s)}"` to `citajo` and `fonto`

## `retposto`

- (CRITICAL ISSUE) Now email move/delete/copy/mark as read takes a long, long time ! Can we speed it up ?
  - the central problem is UI is blocked during those operations, forcing user to wait !
