# Introducing pixi build

## A Python script with one dependency

```toml title="01-python/pixi.toml"
--8<-- "docs/blog/intro-pixi-build/01-python/pixi.toml:dependencies"
```

```python title="01-python/fibtable.py"
--8<-- "docs/blog/intro-pixi-build/01-python/fibtable.py:fib"
```

```python title="01-python/fibtable.py"
--8<-- "docs/blog/intro-pixi-build/01-python/fibtable.py:render"
```

## Run it with a task

```toml title="01-python/pixi.toml"
--8<-- "docs/blog/intro-pixi-build/01-python/pixi.toml:tasks"
```

```console
$ pixi run start
   Fibonacci
┏━━━━┳━━━━━━━━┓
┃  n ┃ fib(n) ┃
┡━━━━╇━━━━━━━━┩
│ 10 │     55 │
│ 20 │   6765 │
│ 30 │ 832040 │
└────┴────────┘
```

## Rewrite the hot loop in Rust (for the performance, obviously)

```rust title="02-rust-cli/fib/src/main.rs"
--8<-- "docs/blog/intro-pixi-build/02-rust-cli/fib/src/main.rs:fib"
```

```console
$ fib 30
832040       # 0.001 s. The Python version also took 0.001 s. A triumph of engineering.
```

## Now Python has to find the binary

```python title="02-rust-cli/fibtable.py"
--8<-- "docs/blog/intro-pixi-build/02-rust-cli/fibtable.py:locate"
```

```python title="02-rust-cli/fibtable.py"
--8<-- "docs/blog/intro-pixi-build/02-rust-cli/fibtable.py:call"
```

## And you have to rebuild it by hand

```toml title="02-rust-cli/pixi.toml"
--8<-- "docs/blog/intro-pixi-build/02-rust-cli/pixi.toml:dependencies"
```

```toml title="02-rust-cli/pixi.toml"
--8<-- "docs/blog/intro-pixi-build/02-rust-cli/pixi.toml:tasks"
```

```console
$ pixi run start
   Compiling fib v0.1.0
    Finished `release` profile [optimized] target(s)
✨ Pixi task (start): python fibtable.py
   Fibonacci
...
```

### The binary is not on `PATH`

### The path is different on Windows

### `cargo` leaks into every environment

### You still cannot hand it to anyone else

## Enter pixi build

```toml title="03-pixi-build/pixi.toml"
--8<-- "docs/blog/intro-pixi-build/03-pixi-build/pixi.toml:dependencies"
```

## The Rust CLI becomes a package

```toml title="03-pixi-build/fib/pixi.toml"
--8<-- "docs/blog/intro-pixi-build/03-pixi-build/fib/pixi.toml:package"
```

## The Python app becomes a package

```toml title="03-pixi-build/pyproject.toml"
--8<-- "docs/blog/intro-pixi-build/03-pixi-build/pyproject.toml"
```

```toml title="03-pixi-build/pixi.toml"
--8<-- "docs/blog/intro-pixi-build/03-pixi-build/pixi.toml:package"
```

## One `pixi install` builds the whole graph

```python title="03-pixi-build/src/fibtable/__init__.py"
--8<-- "docs/blog/intro-pixi-build/03-pixi-build/src/fibtable/__init__.py:call"
```

```console
$ pixi run start
   Compiling fib v0.1.0
    Building fibtable
✨ Pixi task (start): fibtable
   Fibonacci
┏━━━━┳━━━━━━━━┓
┃  n ┃ fib(n) ┃
┡━━━━╇━━━━━━━━┩
│ 10 │     55 │
│ 20 │   6765 │
│ 30 │ 832040 │
└────┴────────┘
```

## A fast inner loop with the dev table

```toml title="03-pixi-build/pixi.toml"
--8<-- "docs/blog/intro-pixi-build/03-pixi-build/pixi.toml:dev"
```

```console
$ pixi run cargo build --manifest-path fib/Cargo.toml
    Finished `dev` profile [unoptimized + debuginfo] target(s)
```

## Ship it with pixi publish

```console
$ pixi publish --target-channel https://prefix.dev/your-channel
# both packages are published: fib and fibtable
```

```console
$ pixi publish --target-dir ./dist
# or just build the .conda artifacts locally
```

## Going further: build CPython from source too

```toml title="04-freethreading/pixi.toml"
--8<-- "docs/blog/intro-pixi-build/04-freethreading/pixi.toml:dependencies"
```

```console
$ pixi run start          # the same app, now on a source-built interpreter
$ pixi run gil
free-threaded: True
```
