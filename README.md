# Repository Coverage

[Full report](https://htmlpreview.github.io/?https://github.com/geoff-davis/aiogzip/blob/python-coverage-comment-action-data/htmlcov/index.html)

| Name                        |    Stmts |     Miss |   Branch |   BrPart |      Cover |   Missing |
|---------------------------- | -------: | -------: | -------: | -------: | ---------: | --------: |
| src/aiogzip/\_\_init\_\_.py |       29 |        0 |       16 |        3 |     93.33% |116-\>exit, 137-\>exit, 155-\>exit |
| src/aiogzip/\_binary.py     |      720 |       44 |      348 |       47 |     91.29% |177, 259, 328, 331, 337, 339-\>350, 374, 417, 426-\>428, 436, 439, 443-\>445, 446, 463, 537, 564, 566, 568, 571, 614, 635, 637, 644, 684-687, 690, 713, 715, 732, 734, 848, 862, 971, 998-999, 1074, 1090, 1094, 1106, 1114, 1130, 1138, 1151, 1167, 1200-\>exit, 1202-\>exit, 1237-\>1241, 1242-\>exit, 1249, 1285-\>exit, 1288-\>exit |
| src/aiogzip/\_common.py     |      181 |        0 |      112 |        5 |     98.29% |310-\>exit, 317-\>exit, 324-\>exit, 325-\>exit, 326-\>exit |
| src/aiogzip/\_engine.py     |       30 |        3 |        6 |        3 |     83.33% |52, 72, 85 |
| src/aiogzip/\_text.py       |      676 |       46 |      308 |       33 |     91.16% |162, 178, 290-291, 317, 329-333, 347, 358, 391-393, 398, 410-412, 429-431, 470, 477, 545, 579, 633, 658, 664-\>667, 670, 710, 751-755, 757, 771, 794-795, 800-\>803, 822, 828-\>831, 902-\>905, 907, 1003-1004, 1016, 1114, 1276-1277, 1300, 1392-\>exit, 1403-\>exit |
| **TOTAL**                   | **1636** |   **93** |  **790** |   **91** | **92.00%** |           |


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