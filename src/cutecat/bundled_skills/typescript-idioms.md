# TypeScript

Use when writing or reviewing TypeScript or JavaScript.

## Types

```ts
// Model the domain so the illegal state cannot be constructed
type Result<T> = { ok: true; value: T } | { ok: false; error: string };

// A discriminated union beats a bag of optionals
type Shape =
  | { kind: "circle"; r: number }
  | { kind: "rect"; w: number; h: number };

// unknown at the boundary, then narrow. never any.
function parse(raw: unknown): Config {
  if (typeof raw !== "object" || raw === null) throw new Error("not an object");
  ...
}
```

- **`any` is a hole in the type system.** `unknown` forces you to check; `any`
  silently disables every check downstream, including the ones you wanted.
- **`strict: true`** in tsconfig, including `strictNullChecks`. Without it the
  types are decoration.
- **Don't assert with `as`** to make an error go away. `as` says "trust me"; you
  are usually wrong, and it fails at runtime instead.
- **`satisfies`** when you want the check without widening the type.

## Traps that bite

- **`==` vs `===`.** Always `===` (and `== null` only if you deliberately mean
  null-or-undefined).
- **Floating promises.** An `async` function you don't `await` swallows its
  rejection. `await` it, or `.catch()` it, or say `void` on purpose.
- **`forEach` with an async callback** does not wait. Use `for…of` with `await`,
  or `Promise.all(map(...))` when they're independent.
- **`Promise.all` rejects on the first failure** and abandons the rest. Use
  `allSettled` when you need every result.
- **Mutating props / shared objects.** Copy (`{...x}`) or use a library that
  enforces it.
- **`this` in a callback.** Arrow functions capture it; `function` does not.
- **`0`, `""` and `NaN` are falsy.** `if (count)` is a bug when 0 is legal. Test
  for `!== undefined`.

## Conventions

Match the project's style and linter; don't import a new one. Prefer the standard
library and the platform (`fetch`, `URL`, `structuredClone`) over a dependency.
Narrow the public surface of a module: export what callers need, nothing else.
