FROM ubuntu:22.04
RUN apt-get update && apt-get install -y openssh-server sudo curl gnupg ca-certificates && \
    mkdir -p /run/sshd && \
    useradd -m -s /bin/bash opspilot && \
    echo "opspilot:test-ssh-password-123" | chpasswd && \
    echo "opspilot ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/opspilot && \
    chmod 440 /etc/sudoers.d/opspilot && \
    sed -i 's/#PermitRootLogin .*/PermitRootLogin no/; s/#PasswordAuthentication .*/PasswordAuthentication yes/' /etc/ssh/sshd_config
EXPOSE 22
CMD ["/usr/sbin/sshd", "-D"]
