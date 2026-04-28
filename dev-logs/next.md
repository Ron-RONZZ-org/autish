# enhancements

- `encik` validation
  - if failed to resolve one or more semantic link(s) ([](#UUID)), throw error listing offending links

# bug fix

- (critical) currently a pytest opens multiple `html` files when ran
  - which disrupts developers working on other tasks while the test run
  - develop alternative less disruptive testing strategy
    -  Update `copilot-instructions.md` and your memory to save this behaviour as default in this repo
