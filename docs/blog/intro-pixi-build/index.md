# Introducing Pixi Build

Pixi is a cross-platform, cross-language package manager and it is awesome!
It is also binary-only.
This means that as far as Pixi is concerned:
- you tell Pixi which packages you want and where it should get it from
- our extremely fast solver finds a combination of packages that satisfies your requirements
- these packages are basically zipped archives that are unpacked in a folder -> that's what we call your environment
- for each environment you typically define Pixi tasks, which you use to do something, typically using some of the packages you just installed

What has been missing until now is a way to *build* a package natively within Pixi.
We are working on making that possible, but first let me first show you with a simple example why that makes many workflows so much more powerful!

## A Simple Python Script

We start with a fresh workspace:

```console
$ pixi init fibtable
$ cd fibtable
```

Then we add both `python` and the Python library `rich` as a dependency

```toml
# pixi.toml
--8<-- "docs/blog/intro-pixi-build/01-python/pixi.toml:dependencies"
```

Let's also write a simple script to calculate the nth Fibonacci number:

```python
# fibtable.py
--8<-- "docs/blog/intro-pixi-build/01-python/fibtable.py:fib"
```

Finally, we make use of our `rich` dependency by wrapping the result into a nice table.

```python
# fibtable.py
--8<-- "docs/blog/intro-pixi-build/01-python/fibtable.py:render"
```

When we then want to run our program, we typically want to first define a task.
Tasks are great since you they serve as documentation in which ways your Pixi workspace can be used and they also allow you to compose multiple tasks into one workflow.

We start with a simple one that simply runs our Python script

```toml
# pixi.toml
--8<-- "docs/blog/intro-pixi-build/01-python/pixi.toml:tasks"
```

And it works!

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

## Rewrite it in Rust

The fibonacci function is now written in pure Python, which is probably slow?
Without measuring anything, let's go ahead and rewrite it in Rust!

Add a Rust crate inside the same workspace:

```console
$ cargo init fib
```

Now we add the same function to our Rust code:

```rust
// fib/src/main.rs
--8<-- "docs/blog/intro-pixi-build/02-rust-cli/fib/src/main.rs:fib"
```

We only have a single function that takes one number and returns one number.
The simplest way of exposing that to the Python code to expose a CLI that takes the input number as argument and then prints the result to stdout.

```rust
// fib/src/main.rs
--8<-- "docs/blog/intro-pixi-build/02-rust-cli/fib/src/main.rs:main"
```

However, how does the Python script know where to find the Rust binary?
Since it isn't an installed package in our environment, we can't just expect it to be in the `PATH`.

The best thing, I can think of right now, is to expect the binary at a certain location relative to the Python script.
This is ugly but it works.

```python
# fibtable.py
--8<-- "docs/blog/intro-pixi-build/02-rust-cli/fibtable.py:locate"
```

We can then run the Rust binary, and extract the output converted as integer.

```python
# fibtable.py
--8<-- "docs/blog/intro-pixi-build/02-rust-cli/fibtable.py:call"
```

In order to be able to build the Rust crate we need to add `rust` to our dependency list.

```toml
# pixi.toml
--8<-- "docs/blog/intro-pixi-build/02-rust-cli/pixi.toml:dependencies"
```

Pixi tasks make the whole thing a bit more bearable.
Now, at least we don't have to remember to pass `--release` when building the CLI and thanks to `depends-on` we can be sure the CLI is built every time 

```toml
# pixi.toml
--8<-- "docs/blog/intro-pixi-build/02-rust-cli/pixi.toml:tasks"
```

When we now execute the `start` task everything is handled transparently:

```console
$ pixi run start
✨ Pixi task (build-cli): cargo build --release --manifest-path fib/Cargo.toml
   Compiling fib v0.1.0
    Finished `release` profile [optimized] target(s)

✨ Pixi task (start): python fibtable.py
   Fibonacci
┏━━━━┳━━━━━━━━┓
┃  n ┃ fib(n) ┃
┡━━━━╇━━━━━━━━┩
│ 10 │     55 │
│ 20 │   6765 │
│ 30 │ 832040 │
└────┴────────┘
```

We made it work, but is it great?
Absolutely not!

We had to hardcode the path to one of our dependencies in the code and that path was even different across operating systems.
Dependencies that are needed for building are mixed with the ones needed for running.
Like we don't need the Rust compiler to run a Rust executable.
All of that makes it very difficult to hand your application to someone else so they can depend on it themselves.
Even if it's only one team working on a single monorepo that workflow scales poorly.

## Enter Pixi Build

What you want instead is that every application and library that you develop on your system translates to its own package that Pixi is aware of.
That way you get all the goodies that you are used to from binary packages like a solver that ensures that your packages are actually compatible.
There also source-specific features like Pixi taking care that dependencies are properly cached and built in the correct order.


```toml
# fib/pixi.toml
--8<-- "docs/blog/intro-pixi-build/03-pixi-build/fib/pixi.toml:package"
```


Add the packaging metadata:

```toml
# pyproject.toml
--8<-- "docs/blog/intro-pixi-build/03-pixi-build/pyproject.toml"
```

```toml
# pixi.toml
--8<-- "docs/blog/intro-pixi-build/03-pixi-build/pixi.toml:package"
```


```toml
# pixi.toml
--8<-- "docs/blog/intro-pixi-build/03-pixi-build/pixi.toml:workspace"
```

## One `pixi install` Builds the Whole Graph

The script now imports the built package instead of locating a binary:

```python
# src/fibtable/__init__.py
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

## A Fast Inner Loop With the Dev Table

Add a dev environment for the quick rebuild cycle:

```toml
# pixi.toml
--8<-- "docs/blog/intro-pixi-build/03-pixi-build/pixi.toml:dev"
```

```console
$ pixi run cargo build --manifest-path fib/Cargo.toml
    Finished `dev` profile [unoptimized + debuginfo] target(s)
```

## Ship It With Pixi Publish

```console
$ pixi publish --target-channel https://prefix.dev/your-channel
# both packages are published: fib and fibtable
```

```console
$ pixi publish --target-dir ./dist
# or just build the .conda artifacts locally
```

## Going Further: Build CPython From Source Too

Swap in a source-built interpreter by adjusting the dependencies:

```toml
# pixi.toml
--8<-- "docs/blog/intro-pixi-build/04-freethreading/pixi.toml:dependencies"
```

```console
$ pixi run start          # the same app, now on a source-built interpreter
$ pixi run gil
free-threaded: True
```
