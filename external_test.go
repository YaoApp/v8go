package v8go_test

import (
	"testing"

	v8 "github.com/YaoApp/v8go"
)

func TestExternal(t *testing.T) {
	t.Parallel()

	ctx := v8.NewContext()
	defer ctx.Isolate().Dispose()
	defer ctx.Close()

	goValue := map[string]interface{}{"foo": "bar"}
	val, err := v8.NewExternal(ctx.Isolate(), goValue)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	if !val.IsYaoExternal() {
		t.Errorf("expected value to be of type External")
	}

	resValue, err := val.External()
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	v, ok := resValue.(map[string]interface{})
	if !ok {
		t.Errorf("expected value to be of type map[string]interface{}")
	}

	if v["foo"] != "bar" {
		t.Errorf("expected value to be 'bar', got %v", v["foo"])
	}

	// Release the external value
	val.Release()
	if v8.ExternalCount() != 0 {
		t.Errorf("expected external count to be 0, got %v", v8.ExternalCount())
	}
}
