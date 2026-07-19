{
  description = "Griffin PowerMate -> MQTT bridge (package + NixOS module)";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

  outputs = { self, nixpkgs }:
    let
      systems = [ "aarch64-linux" "x86_64-linux" ];
      forAllSystems = nixpkgs.lib.genAttrs systems;

      mkPackage = pkgs:
        pkgs.writers.writePython3Bin "powermate-mqtt" {
          libraries = with pkgs.python3Packages; [ evdev paho-mqtt ];
          flakeIgnore = [ "E501" ];
        } (builtins.readFile ./powermate_mqtt.py);
    in
    {
      packages = forAllSystems (system: rec {
        powermate-mqtt = mkPackage nixpkgs.legacyPackages.${system};
        default = powermate-mqtt;
      });

      overlays.default = final: _prev: {
        powermate-mqtt = mkPackage final;
      };

      # The module itself is pure options/config; this wrapper injects our
      # package as the default. Building it from the consumer's `pkgs`
      # (rather than self.packages) means it uses the host system's
      # nixpkgs — no second nixpkgs evaluation, no `follows` needed.
      nixosModules.powermate-mqtt = { pkgs, lib, ... }: {
        imports = [ ./module.nix ];
        services.powermate-mqtt.package = lib.mkDefault (mkPackage pkgs);
      };
      nixosModules.default = self.nixosModules.powermate-mqtt;
    };
}
