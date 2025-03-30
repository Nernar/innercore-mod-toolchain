# Inner Core Mod Toolchain

![Windows](https://img.shields.io/badge/windows-compatible-blue?style=for-the-badge&logo=data:image/svg%2bxml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHZpZXdCb3g9IjAgMCA0ODc1IDQ4NzUiPjxwYXRoIGZpbGw9IiNmZmYiIGQ9Ik0wIDBoMjMxMXYyMzEwSDB6bTI1NjQgMGgyMzExdjIzMTBIMjU2NHpNMCAyNTY0aDIzMTF2MjMxMUgwem0yNTY0IDBoMjMxMXYyMzExSDI1NjQiLz48L3N2Zz4=)
![Linux](https://img.shields.io/badge/linux-compatible-yellowgreen?style=for-the-badge&logoColor=white&logo=linux)

**Inner Core Mod Toolchain for Horizon** is a toolchain that allows you to efficiently develop and build modifications for mobile Minecraft: Bedrock Edition directly from your PC.

## Requirements

To work correctly, this toolchain requires:

- [Python](https://www.python.org/downloads/) 3.7 or higher (recommended 3.8 or higher)
- [node.js](https://nodejs.org/en/download) 10.15.1 or higher (for TypeScript modding), `tsc` version 3 or higher must also be installed (to do this, run `npm install -g tsc`)
- [Android NDK](https://github.com/android/ndk/wiki/Unsupported-Downloads#r16b) version r16b (for C++ modding), otherwise it can be installed by toolchain when needed
- [Java Development Kit 1.8](https://adoptium.net/temurin/releases/?version=8) (for Java modding)

It is obligatory to install only first component, the rest can be installed when necessary.

### Modding with Visual Studio Code

For the best user experience, it is recommended to install [Visual Studio Code](https://code.visualstudio.com/download). This environment is great for modding and can be easily improved with extensions and toolchain itself. This repository already contains all necessary files for easy interaction with this editor.

It is also recommended to install the following extensions:

- ESLint (Microsoft), TSLint now deprecated
- C/C++ Extension Pack (Microsoft)
- Extension Pack for Java (Microsoft)

### Configuration files

There are three types of configurations for managing projects, builds, and the toolchain itself. They describe complete process of building your project.

- make.json — to control the assembly of projects
- toolchain.json — toolchain configuration and basic properties for *make.json*
- template.json — template for subsequent generation *make.json*

Path selections can contain /\*\*/ to select folders and all subfolders, as well as /\* to select all files, /\*.js or /\*.jar to select all files with the desired extension.

## Contributing

Repository requires [Python 3.9 or higher](https://www.python.org/downloads/) installed for successful building, as it uses [package and dependency manager (PDM)](https://pdm-project.org/en/latest/#installation). After downloading repository, open it in your favorite IDE or terminal. You can install package manager using built-in tools:

```sh
python -m pip install pdm
```

Restart terminal and/or IDE to update system variables, then finally install necessary dependencies for project:

```sh
pdm install
```

Before publishing changes, make sure that project builds successfully using `pdm build`, otherwise your pull request will be automatically rejected.
