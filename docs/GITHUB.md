# Repository and data release

Repository: https://github.com/tomatot3/Structure-Generation-of-Interlocking-Floral-Patterns

Track code, prototype inputs, parameter settings, evaluation records, small asset indexes, the website source and documentation in Git. Keep the generated image/geometry collections and comparison inventories in Release attachments.

The release contains:

- `PaperA_Generated_Dataset_1128_Structures_500_Pairs_v1.0.0.zip`
- `PaperA_Experiment_Reproduction_Data_v1.0.0.zip`

Both archives extract into the repository's existing relative layout. Do not add the extracted large folders to Git; `.gitignore` lists them explicitly. Only the image-free source-annotation SVGs belong in the repository. Do not include the source images, local website runtime, saved user edits, feedback submissions, tunnel processes or environment files.

Create the `v1.0.0` release after pushing the code. Attach the two ZIP files to that release. The GitHub-generated Source code ZIP contains only the Git-tracked files, so it does not replace these data attachments.

GitHub limits ordinary Git files to 100 MiB, while each Release attachment may be under 2 GiB. See [large files](https://docs.github.com/en/repositories/working-with-files/managing-large-files/about-large-files-on-github) and [releases](https://docs.github.com/en/repositories/releasing-projects-on-github/about-releases).
