# Readme

We use [pip-tools](https://github.com/jazzband/pip-tools) to manage our pip requirement
files.

## Base Requirements

`base.in` contains requirements for our python environment and
`base.txt` is the corresponding pip requirements file generated by `pip-tools`:

```
pip-compile --output-file=base.txt base.in
```

We install the `base.txt` requirements into the docker image.

## Common Operations

### Add a new base dependency

1. Add a line to `base.in` containing your new dependency
2. In an active virtual environment with `pip-tools` installed.
3. Ensure you are using python 3.9
4. `cd requirements`
5. Run `pip-compile --output-file=base.txt base.in`, review the changes to base.txt,
   commit and push.

### Upgrade an existing dependency

1. Change the version in the corresponding `.in` file.
2. Follow from step 2 above