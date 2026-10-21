class XhsCli < Formula
  include Language::Python::Virtualenv

  desc "CLI for Xiaohongshu (RedNote) - search, read notes, view profiles"
  homepage "https://github.com/jackwener/xhs-cli"
  url "https://files.pythonhosted.org/packages/59/68/9e4518eb56c5002fff53c2f15b0e8ab9526c9c21eb87c2a85f75276bd18b/xhs_cli-0.1.3.tar.gz"
  sha256 "aadb83ab2f11143f85f31269b601a37ec2d548f3f4198e740825c35a2964de34"
  license "Apache-2.0"

  depends_on "python@3.13"

  def install
    python3 = "python3.13"
    venv = libexec

    # Create virtualenv WITH pip (needed to install wheel-only packages)
    system python3, "-m", "venv", venv
    system venv/"bin/pip", "install", "--upgrade", "pip"

    # Install xhs-cli and all dependencies (allows binary wheels for packages
    # that have no sdist: playwright, ua-parser-builtins, geoip2 via uv_build)
    system venv/"bin/pip", "install", "xhs-cli==0.1.3"

    # Symlink the CLI binary
    bin.install_symlink venv/"bin/xhs"
  end

  def caveats
    <<~EOS
      xhs-cli requires the camoufox browser to function.
      After installation, run once to download the browser:

        #{libexec}/bin/python -m camoufox fetch
    EOS
  end

  test do
    assert_match "Usage", shell_output("#{bin}/xhs --help")
  end
end
