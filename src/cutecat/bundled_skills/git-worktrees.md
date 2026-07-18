# Git worktrees

Use when you need to work on two branches at once — reviewing a PR while your
own change is half-finished, comparing behaviour across branches, or running a
long test suite on one branch while editing another.

A worktree gives you a second working directory for the same repository. No
stashing, no `git checkout` dance, no losing your place.

## The commands

```bash
git worktree add ../proj-review origin/feature-x   # a new dir on that branch
git worktree add -b hotfix ../proj-hotfix main     # a new branch, off main
git worktree list                                  # what you have open
git worktree remove ../proj-review                 # when done (dir must be clean)
git worktree prune                                 # tidy up deleted ones
```

Each worktree is a real directory with its own checkout and its own index. They
share one `.git`, so branches, remotes, stashes and objects are common to all.

## Rules

- **One branch per worktree.** Git refuses to check out the same branch twice —
  that's a feature, not an obstacle.
- **Put them beside the repo, not inside it** (`../proj-hotfix`, not
  `./hotfix`), or you'll commit your worktree into your repo.
- **Each worktree needs its own build.** `node_modules`, `.venv`, `target/` are
  not shared. Install per worktree, or the first import will confuse you.
- **`git worktree remove`, not `rm -rf`.** The latter leaves a stale entry;
  `git worktree prune` cleans up after you if you forget.
- **Tell the user where you put it.** A directory appearing beside their repo
  without explanation is alarming.
