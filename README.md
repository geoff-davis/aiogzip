# Repository Coverage

[Full report](https://htmlpreview.github.io/?https://github.com/geoff-davis/aiogzip/blob/python-coverage-comment-action-data/htmlcov/index.html)

| Name                        |    Stmts |     Miss |   Branch |   BrPart |      Cover |   Missing |
|---------------------------- | -------: | -------: | -------: | -------: | ---------: | --------: |
| src/aiogzip/\_\_init\_\_.py |       29 |        0 |       16 |        3 |     93.33% |116-\>exit, 137-\>exit, 155-\>exit |
| src/aiogzip/\_binary.py     |      718 |       51 |      352 |       52 |     90.19% |174, 258, 325, 328, 334, 336-\>347, 371, 414, 420, 428, 431, 435-\>437, 438, 453, 509, 547-548, 555, 557, 559, 562, 602, 621, 623, 625, 627, 667-670, 673, 696, 698, 709, 715, 717, 736, 821, 835, 950, 974-975, 1048, 1064, 1068, 1080, 1088, 1103, 1111, 1124, 1140, 1162, 1166-\>1171, 1168-\>1171, 1198-\>1202, 1203-\>exit, 1210, 1246-\>exit, 1249-\>exit |
| src/aiogzip/\_common.py     |      170 |        0 |      108 |        5 |     98.20% |280-\>exit, 287-\>exit, 294-\>exit, 295-\>exit, 296-\>exit |
| src/aiogzip/\_engine.py     |       30 |        3 |        6 |        3 |     83.33% |52, 72, 85 |
| src/aiogzip/\_text.py       |      657 |       45 |      308 |       32 |     91.19% |159, 175, 285-286, 313, 325-329, 341, 352, 384-386, 389-391, 408-410, 449, 515, 549, 598, 615, 621-\>624, 627, 667, 708-712, 714, 728, 750-751, 756-\>759, 778, 784-\>787, 857-\>860, 862, 958-959, 971, 1079, 1225, 1238-1239, 1262, 1353-\>exit, 1364-\>exit |
| **TOTAL**                   | **1604** |   **99** |  **790** |   **95** | **91.48%** |           |


## Setup coverage badge

Below are examples of the badges you can use in your main branch `README` file.

### Direct image

[![Coverage badge](https://raw.githubusercontent.com/geoff-davis/aiogzip/python-coverage-comment-action-data/badge.svg)](https://htmlpreview.github.io/?https://github.com/geoff-davis/aiogzip/blob/python-coverage-comment-action-data/htmlcov/index.html)

This is the one to use if your repository is private or if you don't want to customize anything.

### [Shields.io](https://shields.io) Json Endpoint

[![Coverage badge](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/geoff-davis/aiogzip/python-coverage-comment-action-data/endpoint.json)](https://htmlpreview.github.io/?https://github.com/geoff-davis/aiogzip/blob/python-coverage-comment-action-data/htmlcov/index.html)

Using this one will allow you to [customize](https://shields.io/endpoint) the look of your badge.
It won't work with private repositories. It won't be refreshed more than once per five minutes.

### [Shields.io](https://shields.io) Dynamic Badge

[![Coverage badge](https://img.shields.io/badge/dynamic/json?color=brightgreen&label=coverage&query=%24.message&url=https%3A%2F%2Fraw.githubusercontent.com%2Fgeoff-davis%2Faiogzip%2Fpython-coverage-comment-action-data%2Fendpoint.json)](https://htmlpreview.github.io/?https://github.com/geoff-davis/aiogzip/blob/python-coverage-comment-action-data/htmlcov/index.html)

This one will always be the same color. It won't work for private repos. I'm not even sure why we included it.

## What is that?

This branch is part of the
[python-coverage-comment-action](https://github.com/marketplace/actions/python-coverage-comment)
GitHub Action. All the files in this branch are automatically generated and may be
overwritten at any moment.