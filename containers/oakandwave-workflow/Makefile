# oakandwave-workflow — unified build system (DM-02, Story 1.1).
#
# `make build` / `make test` behave identically in CI and terminal (R-06):
# every path is derived from this Makefile's own location, so the result does
# not depend on the caller's working directory, and `test` shells out to the
# same pytest oracle in both environments.
#
#   make build   Build the image (default tag oakandwave-workflow:edge).
#   make test    Run the image-toolchain oracle (skips if the image is absent).
#   make ci      build + test — the image exists, so the oracle runs for real.
#   make verify  Ad-hoc smoke: report the kit-dep toolchain versions (Dev Spec §5.B).
#   make clean   Remove the locally built image.
#
# Override tool versions or the base image with, e.g.:
#   make build GO_VERSION=1.24.5 BASE_IMAGE=ghcr.io/agent-of-empires/aoe-dev-sandbox:1.13.0

IMAGE      ?= oakandwave-workflow
TAG        ?= edge
REF        := $(IMAGE):$(TAG)
BASE_IMAGE ?= ghcr.io/agent-of-empires/aoe-dev-sandbox:1.13.0

# Directory of this Makefile → repo root is two levels up (containers/<name>/).
THIS_DIR  := $(patsubst %/,%,$(dir $(abspath $(lastword $(MAKEFILE_LIST)))))
REPO_ROOT := $(abspath $(THIS_DIR)/../..)

DOCKERFILE := $(THIS_DIR)/Dockerfile
ORACLE     := $(REPO_ROOT)/tests/contained-workflow/test_image.py

# Optional per-tool version overrides forwarded to the build as --build-arg.
BUILD_ARGS := --build-arg BASE_IMAGE=$(BASE_IMAGE)
ifdef GO_VERSION
BUILD_ARGS += --build-arg GO_VERSION=$(GO_VERSION)
endif
ifdef SHELLCHECK_VERSION
BUILD_ARGS += --build-arg SHELLCHECK_VERSION=$(SHELLCHECK_VERSION)
endif
ifdef SHFMT_VERSION
BUILD_ARGS += --build-arg SHFMT_VERSION=$(SHFMT_VERSION)
endif
ifdef GLAB_VERSION
BUILD_ARGS += --build-arg GLAB_VERSION=$(GLAB_VERSION)
endif
ifdef TRIVY_VERSION
BUILD_ARGS += --build-arg TRIVY_VERSION=$(TRIVY_VERSION)
endif
ifdef BAO_VERSION
BUILD_ARGS += --build-arg BAO_VERSION=$(BAO_VERSION)
endif
ifdef AWSCLI_VERSION
BUILD_ARGS += --build-arg AWSCLI_VERSION=$(AWSCLI_VERSION)
endif
ifdef SDLC_PROBE_REF
BUILD_ARGS += --build-arg SDLC_PROBE_REF=$(SDLC_PROBE_REF)
endif

.PHONY: build test ci verify clean

build:
	docker build $(BUILD_ARGS) -f $(DOCKERFILE) -t $(REF) $(REPO_ROOT)

# The oracle self-skips when docker or the image is unavailable, so `make test`
# is safe to run without a build; `make ci` builds first so it runs for real.
# OAKANDWAVE_IMAGE lets the oracle target this Makefile's tag.
test:
	OAKANDWAVE_IMAGE=$(REF) python3 -m pytest $(ORACLE) -q

ci: build
	OAKANDWAVE_IMAGE=$(REF) OAKANDWAVE_REQUIRE_IMAGE=1 python3 -m pytest $(ORACLE) -q

verify:
	docker run --rm --entrypoint sh $(REF) -c '\
		set -e; \
		go version; \
		trivy --version; \
		shellcheck --version; \
		shfmt --version; \
		glab --version; \
		bao version; \
		aws --version'

clean:
	- docker image rm $(REF)
