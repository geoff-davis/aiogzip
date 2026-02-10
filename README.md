# Repository Coverage

[Full report](https://htmlpreview.github.io/?https://github.com/geoff-davis/aiogzip/blob/python-coverage-comment-action-data/htmlcov/index.html)

| Name                        |    Stmts |     Miss |   Branch |   BrPart |      Cover |   Missing |
|---------------------------- | -------: | -------: | -------: | -------: | ---------: | --------: |
| src/aiogzip/\_\_init\_\_.py |       19 |        0 |       10 |        0 |    100.00% |           |
| src/aiogzip/\_binary.py     |      458 |       47 |      214 |       44 |     85.86% |110, 152, 196, 199, 205, 207->218, 230, 268, 274, 282, 285, 289->291, 292, 307, 316, 325, 328, 346, 348, 350, 352, 374, 378, 401, 403, 414, 420, 422, 439, 472, 485, 487, 495-499, 588, 594, 613, 650, 654, 660-661, 666, 669, 675, 706->710, 711->exit, 718, 742->exit, 744->exit, 758 |
| src/aiogzip/\_common.py     |      158 |       15 |       96 |       11 |     86.61% |91, 93, 103, 189-194, 203-206, 209-210, 259->exit, 266->exit, 273->exit, 274->exit, 275->exit |
| src/aiogzip/\_text.py       |      338 |       27 |      168 |       20 |     89.92% |110, 173, 197, 208, 231-233, 236-238, 277, 333, 343-344, 397->393, 417, 452->457, 454->457, 459-460, 469-470, 482, 489, 497, 565, 600-601, 692->exit, 710->exit, 712-715 |
| **TOTAL**                   |  **973** |   **89** |  **488** |   **75** | **87.68%** |           |


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