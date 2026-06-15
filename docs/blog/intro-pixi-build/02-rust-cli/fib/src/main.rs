use std::env;

// --8<-- [start:fib]
/// The nth Fibonacci number.
fn fib(n: u64) -> u64 {
    let (mut a, mut b) = (0, 1);
    for _ in 0..n {
        (a, b) = (b, a + b);
    }
    a
}
// --8<-- [end:fib]

// --8<-- [start:main]
fn main() {
    let n: u64 = env::args().nth(1).unwrap().parse().unwrap();
    println!("{}", fib(n));
}
// --8<-- [end:main]
