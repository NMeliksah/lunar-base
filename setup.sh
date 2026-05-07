#!/usr/bin/env bash
echo === Lunar Base setup ===

check_dir_empty() {
    local dir="$1"
    if [ -d $dir ]; then
        if [-z "$( ls -A $dir )" ]; then
            return 0
        fi
        return 1
    fi
    return 0
}


if [ ! -d .venv ]; then
    echo Creating virtual environment in .venv ...
    python -m venv .venv
    if [ $? -eq 1 ]; then
        echo Failed to create virtual environment. Make sure Python 3.10+ is installed and accessible as "python".
    fi
else
    echo Virtual environment already exists.
fi

echo Installing / updating app dependencies ...

source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r web/requirements.txt
if [ $? -eq 1 ]; then
    echo Dependency install failed. Check the messages above.
fi

echo === Master data ===

check_dir_empty "data/masterdata"
if [ $? -eq 0 ]; then
    MD_SCRIPT=../lunar-scripts/dump_masterdata.py
    MD_INPUT=../lunar-tear/server/assets/release/20240404193219.bin.e

    if [ ! -f $MD_SCRIPT ]; then
        echo Skipping master-data dump: lunar-scripts not found at ..\lunar-scripts\
        echo Stages 1+ need the dump. To dump later, see README.md and re-run setup.bat.
        exit 1
    fi

    if [ ! -f $MD_INPUT ]; then
        echo Skipping master-data dump: master data binary not found at:
        echo   $MD_INPUT
        echo Populate ../lunar-tear/server/assets/ first, then re-run setup.sh.
        exit 1
    fi


    echo "Installing master-data dump dependencies (one-time, into .venv) ..."
    python -m pip install pycryptodome msgpack lz4
    if [ $? -eq 1 ]; then
        echo.
        echo Failed to install dump dependencies.
        exit 1
    fi

    echo Dumping master data to data\masterdata\ ...
    pushd ../lunar-scripts
    python dump_masterdata.py --input "../lunar-tear/server/assets/release/20240404193219.bin.e" --output "../lunar-base/data/masterdata"
    DUMP_RC=$?
    popd

    if [ ! $DUMP_RC -eq 0 ]; then
        echo "Master data dump failed (exit code %DUMP_RC%)."
        exit 1
    fi
else
    echo Master data already dumped at data/masterdata/ -- skipping.
fi

echo === Names extraction ===

check_dir_empty "data/names"
if [ $? -eq 0 ]; then
    REVISIONS_DIR="../lunar-tear/server/assets/revisions"
    check_dir_empty $REVISIONS_DIR
    if [ $? -eq 0 ]; then
        echo lunar-tear revisions tree not found at:
        echo $REVISIONS_DIR
        exit 1
    fi

    echo Extracting English names from text bundles ...
    python tools/extract_names.py
    if [ $? -eq 1 ]; then
        echo Names extraction failed.
        exit 1
    fi
else
    echo Names already extracted at data/names/ -- skipping.
fi


echo === Grant shim build ===

if ! command -v go $>/dev/null; then
    echo "Go is not on PATH. Skipping grant shim build."
    echo "Stage 1+ needs Go ^(1.25+^). Install it and re-run setup.bat."
    exit 1
fi

if [ ! -f "../lunar-tear/server/go.mod" ]; then
    echo Skipping shim build: lunar-tear/server not found at ../lunar-tear/server/
    echo Re-run setup.sh once lunar-tear is in place.
    exit 1
fi

if [ ! -f "tools/grant/src/main.go" ]; then
    echo Skipping shim build: tools/grant/src/main.go missing.
    exit 1
fi

echo Copying shim sources into lunar-tear/server/cmd/lunar-base-grant\ ...

mkdir -p "../lunar-tear/server/cmd/lunar-base-grant"
cp tools/grant/src/*.go ../lunar-tear/server/cmd/lunar-base-grant/

if [ $? -eq 1 ]; then
    echo Failed to copy shim sources. Stage 1+ will not work.
    exit 1
fi

echo Building tools/grant/grant ...

CURRENT_DIR=$(pwd)
pushd ../lunar-tear/server
go build -o "$CURRENT_DIR/grant/grant" ./cmd/lunar-base-grant/
BUILD_RC=$?
popd

if [ ! $? -eq 0 ]; then
    echo "grant build failed (exit code $BUILD_RC). Stage 1+ will not work."
    echo 'Check that lunar-tear/server compiles cleanly: cd to it and run "go build ./..."'.
    exit 1
fi
echo Built: tools/grant/grant

echo Setup complete. Run run-lunar-base.sh to start the app.
