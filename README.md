# Repository Coverage

[Full report](https://htmlpreview.github.io/?https://github.com/geoff-davis/aiogzip/blob/python-coverage-comment-action-data/htmlcov/index.html)

| Name                        |    Stmts |     Miss |   Branch |   BrPart |      Cover |   Missing |
|---------------------------- | -------: | -------: | -------: | -------: | ---------: | --------: |
| src/aiogzip/\_\_init\_\_.py |       19 |        0 |       10 |        0 |    100.00% |           |
| src/aiogzip/\_binary.py     |      507 |       49 |      238 |       49 |     86.31% |113, 159, 214, 217, 223, 225->236, 260, 298, 304, 312, 315, 319->321, 322, 337, 346, 355, 358, 376, 378, 380, 382, 404, 408, 431, 433, 444, 450, 452, 469, 502, 515, 517, 525-529, 618, 637, 674, 678, 684-685, 690, 698, 702, 712, 720->722, 728, 739, 742->746, 744->746, 773->777, 778->exit, 785, 809->exit, 811->exit, 825 |
| src/aiogzip/\_common.py     |      162 |       15 |       98 |       11 |     86.92% |92, 94, 107, 193-198, 207-210, 213-214, 263->exit, 270->exit, 277->exit, 278->exit, 279->exit |
| src/aiogzip/\_text.py       |      353 |       29 |      170 |       20 |     89.87% |112, 167-168, 185, 215, 226, 248-250, 253-255, 294, 350, 360-361, 414->410, 434, 469->474, 471->474, 476-477, 486-487, 499, 506, 514, 582, 617-618, 709->exit, 728->exit, 730-733 |
| **TOTAL**                   | **1041** |   **93** |  **516** |   **80** | **87.86%** |           |


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