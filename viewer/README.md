# Gait data viewer

The static viewer loads `synchronized_walk.csv` and renders selected channels as
stacked Plotly subplots with a shared FID axis.

## GitHub Pages deployment

GitHub does not permit a repository workflow token to create the repository's
initial Pages site. A repository owner must perform this one-time setup:

1. Open **Settings → Pages** in the GitHub repository.
2. Under **Build and deployment**, set **Source** to **GitHub Actions**.
3. Rerun the **Deploy gait data viewer** workflow.

Subsequent pushes to `study-gait-pattern` that change the viewer, deployment
workflow, or synchronized dataset deploy automatically. The deployment artifact
contains only the viewer assets and `synchronized_walk.csv`; it excludes the raw
recordings and video.
