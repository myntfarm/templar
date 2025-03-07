








```
curl https://sh.rustup.rs -sSf | sh -s -- -y
. "$HOME/.cargo/env"
rustup default stable
rustup update nightly
rustup target add wasm32-unknown-unknown --toolchain nightly
```
