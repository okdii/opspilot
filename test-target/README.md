# OpsPilot Test Target Server

A test server for OpsPilot agent development and manual testing. Spin up a Linux VM locally, register it in OpsPilot, and verify the agent works end-to-end.

---

## Option 1 — Multipass (Recommended, Mac + Windows)

[Multipass](https://multipass.run/) by Canonical spins up Ubuntu VMs in seconds. Works on both Mac and Windows with no extra configuration.

### Install

- **Mac:** `brew install --cask multipass`
- **Windows:** download the installer from [multipass.run](https://multipass.run/)

### Create the VM

```bash
multipass launch --name opspilot-test lts
```

### Configure SSH + opspilot user

```bash
multipass shell opspilot-test
```

Inside the VM, run:

```bash
sudo apt-get update && sudo apt-get install -y openssh-server
sudo useradd -m -s /bin/bash opspilot
echo "opspilot:test-ssh-password-123" | sudo chpasswd
echo "opspilot ALL=(ALL) NOPASSWD:ALL" | sudo tee /etc/sudoers.d/opspilot
sudo chmod 440 /etc/sudoers.d/opspilot
sudo sed -i 's/#PasswordAuthentication .*/PasswordAuthentication yes/' /etc/ssh/sshd_config
sudo systemctl restart ssh
exit
```

### Get the VM's IP

```bash
multipass info opspilot-test | grep IPv4
```

### Add to OpsPilot

| Field    | Value                   |
|----------|-------------------------|
| Host     | IP from the step above  |
| Port     | `22`                    |
| User     | `opspilot`              |
| Password | `test-ssh-password-123` |

### Manage the VM

```bash
multipass stop opspilot-test          # pause
multipass start opspilot-test         # resume
multipass delete opspilot-test && multipass purge   # remove permanently
```

---

## Option 2 — Lima (Mac only)

[Lima](https://lima-vm.io/) is a lightweight VM tool for macOS. Works on both Intel and Apple Silicon.

### Install

```bash
brew install lima
```

### Create the VM

```bash
limactl start --name=opspilot-test template://ubuntu-lts
```

### Configure SSH + opspilot user

```bash
limactl shell opspilot-test
```

Inside the VM:

```bash
sudo apt-get update && sudo apt-get install -y openssh-server
sudo useradd -m -s /bin/bash opspilot
echo "opspilot:test-ssh-password-123" | sudo chpasswd
echo "opspilot ALL=(ALL) NOPASSWD:ALL" | sudo tee /etc/sudoers.d/opspilot
sudo chmod 440 /etc/sudoers.d/opspilot
sudo sed -i 's/#PasswordAuthentication .*/PasswordAuthentication yes/' /etc/ssh/sshd_config
sudo systemctl restart ssh
exit
```

### Get the VM's IP

```bash
limactl shell opspilot-test -- ip addr show lima0 | grep 'inet '
```

Use the printed IP (e.g. `192.168.105.2`) as the host in OpsPilot on port `22`.

### Manage the VM

```bash
limactl stop opspilot-test
limactl start opspilot-test
limactl delete opspilot-test    # remove permanently
```

---

## Option 3 — VirtualBox + Vagrant (Mac + Windows fallback)

Use this if Multipass is not available or if you need more control over the VM resources.

### Prerequisites

- [VirtualBox](https://www.virtualbox.org/)
- [Vagrant](https://www.vagrantup.com/)

### Create a Vagrantfile

Create a folder and add this `Vagrantfile`:

```ruby
Vagrant.configure("2") do |config|
  config.vm.box = "ubuntu/jammy64"
  config.vm.network "forwarded_port", guest: 22, host: 2222, id: "ssh_custom"
  config.vm.provider "virtualbox" do |vb|
    vb.memory = "1024"
    vb.cpus = 1
  end
  config.vm.provision "shell", inline: <<-SHELL
    apt-get update && apt-get install -y openssh-server
    useradd -m -s /bin/bash opspilot
    echo "opspilot:test-ssh-password-123" | chpasswd
    echo "opspilot ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/opspilot
    chmod 440 /etc/sudoers.d/opspilot
    sed -i 's/#PasswordAuthentication .*/PasswordAuthentication yes/' /etc/ssh/sshd_config
    systemctl restart ssh
  SHELL
end
```

```bash
vagrant up
```

### Add to OpsPilot

| Field    | Value                   |
|----------|-------------------------|
| Host     | `localhost`             |
| Port     | `2222`                  |
| User     | `opspilot`              |
| Password | `test-ssh-password-123` |

### Manage the VM

```bash
vagrant halt        # stop
vagrant up          # start
vagrant destroy     # remove permanently
```

---

## Comparison

| Option           | Mac | Windows | Setup time | Notes                              |
|------------------|-----|---------|------------|------------------------------------|
| Multipass        | ✅  | ✅      | ~3 min     | Recommended. Simplest cross-platform VM. |
| Lima             | ✅  | ❌      | ~3 min     | Mac-native, Apple Silicon friendly |
| VirtualBox+Vagrant | ✅ | ✅    | ~5 min     | More control, heavier install      |

---

## Default Credentials

| Field    | Value                   |
|----------|-------------------------|
| User     | `opspilot`              |
| Password | `test-ssh-password-123` |

> For local development only. Do not expose this VM to the public internet.
