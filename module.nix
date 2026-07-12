# NixOS module for the PowerMate -> MQTT bridge.
# Deliberately self-contained: takes the package via an option, so it
# composes with any nixpkgs the consumer uses.
{ config, lib, ... }:
let
  cfg = config.services.powermate-mqtt;
in
{
  options.services.powermate-mqtt = {
    enable = lib.mkEnableOption "Griffin PowerMate to MQTT bridge";

    package = lib.mkOption {
      type = lib.types.package;
      description = "The powermate-mqtt package to run (set by the flake's module by default).";
    };

    broker = lib.mkOption {
      type = lib.types.str;
      example = "192.168.1.10";
      description = "MQTT broker hostname or IP.";
    };

    brokerPort = lib.mkOption {
      type = lib.types.port;
      default = 1883;
      description = "MQTT broker port.";
    };

    topicPrefix = lib.mkOption {
      type = lib.types.str;
      default = "powermate";
      description = "Prefix for published topics (<prefix>/rotate, <prefix>/button, ...).";
    };

    longPressMs = lib.mkOption {
      type = lib.types.ints.positive;
      default = 600;
      description = "Hold duration before a long_press is emitted.";
    };

    ticksPerStep = lib.mkOption {
      type = lib.types.ints.positive;
      default = 1;
      description = ''
        Raw encoder ticks per published rotation event. Leave at 1
        (pass-through). Set to 2 if a marginal USB link duplicates
        every report (one MQTT event per pair of ticks).
      '';
    };

    device = lib.mkOption {
      type = lib.types.str;
      default = "/dev/input/powermate";
      description = "Input device path (the udev rule below creates this symlink).";
    };
  };

  config = lib.mkIf cfg.enable {
    # Stable symlink + start the service whenever the knob is plugged in.
    services.udev.extraRules = ''
      SUBSYSTEM=="input", ATTRS{idVendor}=="077d", ATTRS{idProduct}=="0410", \
        KERNEL=="event*", SYMLINK+="input/powermate", MODE="0660", GROUP="input", \
        TAG+="systemd", ENV{SYSTEMD_WANTS}+="powermate-mqtt.service"
    '';

    systemd.services.powermate-mqtt = {
      description = "PowerMate to MQTT bridge";
      after = [ "network-online.target" ];
      wants = [ "network-online.target" ];
      environment = {
        PM_DEVICE = cfg.device;
        PM_BROKER = cfg.broker;
        PM_PORT = toString cfg.brokerPort;
        PM_TOPIC_PREFIX = cfg.topicPrefix;
        PM_LONG_PRESS_MS = toString cfg.longPressMs;
        PM_TICKS_PER_STEP = toString cfg.ticksPerStep;
      };
      serviceConfig = {
        ExecStart = lib.getExe cfg.package;
        Restart = "on-failure";
        RestartSec = 2;
        DynamicUser = true;
        SupplementaryGroups = [ "input" ];
        # Hardening
        ProtectSystem = "strict";
        ProtectHome = true;
        PrivateTmp = true;
        NoNewPrivileges = true;
      };
    };
  };
}
