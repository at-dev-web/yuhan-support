# To learn more about how to use Nix to configure your environment
# see: https://developers.google.com/idx/guides/customize-idx-env
{ pkgs, ... }: {
  # Which nixpkgs channel to use.
  channel = "stable-24.11"; # or "unstable"
  # Use https://search.nixos.org/packages to find packages
  packages = [
  pkgs.python312
  pkgs.python312Packages.pip
  ];
  # Sets environment variables in the workspace
  
  idx = {
    # Search for the extensions you want on https://open-vsx.org/ and use "publisher.id"
    extensions = [
      # "vscodevim.vim"
      "google.gemini-cli-vscode-ide-companion"
    ];
    # Enable previews
    previews = {
  enable = true;
  previews = {
    web = {
      command = [
        "./.venv/bin/python"
  "-m"
  "streamlit"
  "run"
  "app.py"
  "--server.port"
  "$PORT"
  "--server.address"
  "0.0.0.0"
  "--server.enableCORS"
  "false"
      ];
      manager = "web";
    };
  };
};

    # Workspace lifecycle hooks
    workspace = {
      # Runs when a workspace is first created
      onCreate = {
        # Example: install JS dependencies from NPM
        # npm-install = "npm install";
        # Open editors for the following files by default, if they exist:
        default.openFiles = [ ".idx/dev.nix" "README.md" ];
      };
      # Runs when the workspace is (re)started
      onStart = {
        # Example: start a background task to watch and re-build backend code
        # watch-backend = "npm run watch-backend";
      };
    };
  };
}
